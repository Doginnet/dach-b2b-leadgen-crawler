"""Streaming bzip2 JSONL ingestion of 1,000,000+ German Handelsregister companies from OffeneRegister."""

from __future__ import annotations

import bz2
import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from config.settings import settings
from src.extractors.impressum import classify_legal_form
from src.extractors.scoring import normalize_brand_slug
from src.models.lead import RegistryCompany
from src.storage.duckdb_store import DuckDBStore

PLZ_CITY_RE = re.compile(r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\- ()/]{1,40})")
DIGITS_RE = re.compile(r"\d+")
ACTIVE_LEADERSHIP_ROLES = (
    "geschäftsführer",
    "geschaeftsfuehrer",
    "vorstand",
    "inhaber",
    "persönlich haftender gesellschafter",
    "direktor",
    "liquidator",
)


def parse_offeneregister_record(raw: dict[str, Any]) -> RegistryCompany | None:
    """Transform a raw OffeneRegister JSON object into a normalized RegistryCompany."""
    company_number = str(raw.get("company_number") or "").strip()
    legal_name = str(raw.get("name") or "").strip()
    if not company_number or not legal_name:
        return None

    status = str(raw.get("current_status") or "").strip().lower()
    if status and status not in ("currently registered", "active"):
        return None

    attrs = raw.get("all_attributes") or {}
    reg_type = str(attrs.get("_registerArt") or "").strip().upper()
    raw_reg_num = str(attrs.get("_registerNummer") or "").strip()
    num_match = DIGITS_RE.search(raw_reg_num)
    reg_id = num_match.group(0) if num_match else ""

    native_num = str(attrs.get("native_company_number") or "").strip()
    federal_state = str(attrs.get("federal_state") or "").strip()
    city = str(attrs.get("registered_office") or "").strip()
    address = str(raw.get("registered_address") or "").strip()

    postal_code = ""
    if address:
        plz_match = PLZ_CITY_RE.search(address)
        if plz_match:
            postal_code = plz_match.group(1)
            if not city:
                city = plz_match.group(2).strip(" .,")

    ceos: list[str] = []
    seen_officers: set[str] = set()
    for officer in raw.get("officers") or []:
        if not isinstance(officer, dict):
            continue
        if officer.get("end_date") or officer.get("dismissed"):
            continue
        pos = str(officer.get("position") or "").lower()
        name = str(officer.get("name") or "").strip()
        if not name or len(name) < 4:
            continue
        if (not pos or any(role in pos for role in ACTIVE_LEADERSHIP_ROLES)) and name.lower() not in seen_officers:
            seen_officers.add(name.lower())
            ceos.append(name)

    return RegistryCompany(
        company_number=company_number,
        register_type=reg_type,
        register_id=reg_id,
        native_company_number=native_num,
        legal_name=legal_name,
        brand_slug=normalize_brand_slug(legal_name),
        legal_form=classify_legal_form(legal_name),
        current_status=status or "currently registered",
        federal_state=federal_state,
        city=city,
        postal_code=postal_code,
        registered_address=address[:220],
        ceo_names=ceos[:4],
    )


def stream_offeneregister_companies(
    target_rows: int = 1_000_000,
    dump_url: str | None = None,
    local_bz2_path: Path | None = None,
) -> Iterator[RegistryCompany]:
    """Stream and decompress multi-stream pbzip2 OffeneRegister JSONL lines on-the-fly without 4GB disk extraction."""
    decompressor = bz2.BZ2Decompressor()
    pending = bytearray()
    yielded = 0

    def _consume_chunk(compressed_bytes: bytes) -> Iterator[RegistryCompany]:
        nonlocal decompressor, yielded, pending
        buf = compressed_bytes
        while buf and yielded < target_rows:
            decompressed = decompressor.decompress(buf)
            if decompressed:
                pending.extend(decompressed)
                if b"\n" in pending:
                    lines = pending.split(b"\n")
                    pending = bytearray(lines.pop())
                    for raw_line in lines:
                        if not raw_line:
                            continue
                        try:
                            payload = json.loads(raw_line.decode("utf-8", errors="replace"))
                        except json.JSONDecodeError:
                            continue
                        entity = parse_offeneregister_record(payload)
                        if entity is not None:
                            yielded += 1
                            yield entity
                            if yielded >= target_rows:
                                return

            # OffeneRegister uses multi-stream pbzip2; roll over unused_data into a fresh decompressor
            if decompressor.eof:
                buf = decompressor.unused_data
                decompressor = bz2.BZ2Decompressor()
            else:
                buf = b""

    if local_bz2_path and local_bz2_path.exists():
        logger.info(f"Streaming OffeneRegister from local archive: {local_bz2_path}")
        with open(local_bz2_path, "rb") as fh:
            while yielded < target_rows:
                chunk = fh.read(524_288)
                if not chunk:
                    break
                yield from _consume_chunk(chunk)
        return

    url = dump_url or settings.offeneregister_dump_url
    logger.info(f"Streaming {target_rows:,} active German companies over HTTP from {url}")
    with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes(chunk_size=524_288):
                yield from _consume_chunk(chunk)
                if yielded >= target_rows:
                    break


def seed_handelsregister_to_duckdb(
    store: DuckDBStore,
    target_rows: int = 1_000_000,
    batch_size: int = 50_000,
    export_parquet: bool = True,
    local_bz2_path: Path | None = None,
) -> dict[str, Any]:
    """Stream 1M+ Handelsregister records into DuckDB via PyArrow batches and export ZSTD Parquet."""
    t0 = time.perf_counter()
    buffer: list[RegistryCompany] = []
    inserted = 0

    for company in stream_offeneregister_companies(
        target_rows=target_rows,
        local_bz2_path=local_bz2_path,
    ):
        buffer.append(company)
        if len(buffer) >= batch_size:
            inserted += store.bulk_insert_registry_arrow(buffer)
            buffer.clear()
            elapsed = time.perf_counter() - t0
            rate = int(inserted / max(elapsed, 0.001))
            logger.info(f"Ingested {inserted:,}/{target_rows:,} Handelsregister entities ({rate:,} rows/s)")

    if buffer:
        inserted += store.bulk_insert_registry_arrow(buffer)
        buffer.clear()

    parquet_path_str = ""
    parquet_mb = 0.0
    if export_parquet and inserted > 0:
        p_path = store.export_registry_parquet()
        parquet_path_str = str(p_path)
        if p_path.exists():
            parquet_mb = round(p_path.stat().st_size / (1024 * 1024), 2)
        logger.info(f"Exported {inserted:,} rows to ZSTD Parquet: {p_path} ({parquet_mb} MB)")

    total_sec = round(time.perf_counter() - t0, 2)
    return {
        "inserted_rows": inserted,
        "elapsed_seconds": total_sec,
        "rows_per_second": int(inserted / max(total_sec, 0.01)),
        "parquet_path": parquet_path_str,
        "parquet_size_mb": parquet_mb,
    }
