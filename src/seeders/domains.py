"""DACH (.de / .at / .ch) commercial domain frontier loader from Tranco Top-1M + curated B2B/E-Com seeds."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import httpx
from loguru import logger

from config.settings import settings
from src.extractors.scoring import normalize_brand_slug
from src.storage.duckdb_store import DuckDBStore

DACH_TLDS = {"de", "at", "ch"}

# Exclude giant portals, ISPs, media, public universities, and government domains so crawl targets B2B/E-Com
NON_TARGET_DOMAINS = {
    "google.de",
    "google.at",
    "google.ch",
    "amazon.de",
    "ebay.de",
    "wikipedia.de",
    "youtube.de",
    "t-online.de",
    "gmx.net",
    "gmx.de",
    "gmx.at",
    "gmx.ch",
    "web.de",
    "spiegel.de",
    "bild.de",
    "zeit.de",
    "faz.net",
    "sueddeutsche.de",
    "welt.de",
    "focus.de",
    "stern.de",
    "tagesschau.de",
    "zdf.de",
    "ard.de",
    "ndr.de",
    "wdr.de",
    "br.de",
    "heise.de",
    "chip.de",
    "golem.de",
    "computerbild.de",
    "bund.de",
    "arbeitsagentur.de",
    "berlin.de",
    "muenchen.de",
    "hamburg.de",
    "koeln.de",
    "dhl.de",
    "deutschepost.de",
    "bahn.de",
    "post.at",
    "post.ch",
    "sbb.ch",
    "orf.at",
    "srf.ch",
    "20min.ch",
    "blick.ch",
    "derstandard.at",
    "krone.at",
    "kurier.at",
}

NON_B2B_SUBSTRINGS = (
    "uni-",
    "tu-",
    "fh-",
    "hochschule",
    "polizei",
    "landkreis",
    "stadt-",
    "gemeinde-",
    "sparkasse",
    "volksbank",
    "klinikum",
)

# High-signal DACH E-Commerce (Shopware/Shopify/WooCommerce) & B2B SaaS domains guaranteed at top of frontier
CURATED_DACH_COMMERCIAL_SEEDS: tuple[tuple[str, int], ...] = (
    ("thomann.de", 1200),
    ("flaconi.de", 2400),
    ("bergfreunde.de", 2800),
    ("rosebikes.de", 2900),
    ("teufel.de", 3100),
    ("cyberport.de", 3200),
    ("bike-components.de", 3400),
    ("reuter.de", 3600),
    ("lampenwelt.de", 3800),
    ("home24.de", 3900),
    ("westwing.de", 4100),
    ("personio.de", 4200),
    ("lexoffice.de", 4300),
    ("sevdesk.de", 4400),
    ("babbel.com", 4500),
    ("snocks.com", 4600),
    ("purelei.com", 4700),
    ("jeanlen.de", 4800),
    ("ankerkraut.de", 4900),
    ("koawach.de", 5000),
    ("armedangels.com", 5100),
    ("engelbert-strauss.de", 5200),
    ("beyerdynamic.de", 5300),
    ("miele.de", 5400),
    ("viessmann.de", 5500),
    ("stihl.de", 5600),
    ("zeiss.de", 5700),
    ("festo.com", 5800),
    ("trumpf.com", 5900),
    ("wuerth.de", 6000),
    ("bueromarkt-ag.de", 6100),
    ("notebooksbilliger.de", 6200),
    ("galeria.de", 6300),
    ("douglas.de", 6400),
    ("breuninger.com", 6500),
    ("sportscheck.com", 6600),
    ("globetrotter.de", 6700),
    ("musik-produktiv.de", 6800),
    ("mindfactory.de", 6900),
    ("alternate.de", 7000),
    ("conrad.de", 7100),
    ("reichelt.de", 7200),
    ("contorion.de", 7300),
    ("kaiserkraft.de", 7400),
    ("schaefer-shop.de", 7500),
    ("flyeralarm.com", 7600),
    ("wir-machen-druck.de", 7700),
    ("cewe.de", 7800),
    ("posterxxl.de", 7900),
    ("frosta.de", 8000),
    ("ritter-sport.de", 8100),
    ("haribo.com", 8200),
    ("melitta.de", 8300),
    ("tchibo.de", 8400),
    ("rossmann.de", 8500),
    ("dm.de", 8600),
    ("alnatura.de", 8700),
    ("shop-apotheke.com", 8800),
    ("docmorris.de", 8900),
    ("medpex.de", 9000),
    ("misterspex.de", 9100),
    ("fielmann.de", 9200),
    ("kapten-son.com", 9300),
    ("paul-hewitt.com", 9400),
    ("holzkern.com", 9500),
    ("giesswein.com", 9600),
    ("waterdrop.de", 9700),
    ("yfood.eu", 9800),
    ("esn.com", 9900),
    ("morenutrition.de", 9950),
    ("motel-one.com", 10100),
    ("sixt.de", 10200),
    ("flixbus.de", 10300),
    ("check24.de", 10400),
    ("clark.de", 10500),
    ("scalable.capital", 10600),
    ("raisin.com", 10700),
    ("mambu.com", 10800),
    ("contentful.com", 10900),
    ("deepL.com", 11000),
    ("shopware.com", 11100),
    ("spryker.com", 11200),
    ("commercetools.com", 11300),
    ("ninox.com", 11400),
    ("staffbase.com", 11500),
    ("parloa.com", 11600),
    ("aleph-alpha.com", 11700),
    ("hetzner.com", 11800),
    ("ionos.de", 11900),
    ("strato.de", 12000),
)


def download_tranco_zip(cache_dir: Path | None = None, url: str | None = None) -> Path:
    """Download and cache the 9.3 MB Tranco Top-1M domain archive."""
    target_dir = Path(cache_dir or settings.cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / "tranco_top_1m.csv.zip"
    if archive_path.exists() and archive_path.stat().st_size > 1_000_000:
        logger.info(f"Using cached Tranco Top-1M archive: {archive_path}")
        return archive_path

    download_url = url or settings.tranco_top_1m_url
    logger.info(f"Downloading Tranco Top-1M domain index from {download_url}")
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(download_url)
        resp.raise_for_status()
        archive_path.write_bytes(resp.content)
    return archive_path


def extract_dach_commercial_domains(
    archive_path: Path,
    max_domains: int = 50_000,
) -> list[tuple[str, str, int | None, str]]:
    """Extract clean registrable .de/.at/.ch B2B & commercial domains + curated DACH seeds."""
    results: list[tuple[str, str, int | None, str]] = []
    seen: set[str] = set()

    for raw_dom, synthetic_rank in CURATED_DACH_COMMERCIAL_SEEDS:
        dom = raw_dom.lower().strip()
        tld = dom.rsplit(".", 1)[-1]
        seen.add(dom)
        results.append((dom, tld, synthetic_rank, normalize_brand_slug(dom)))

    with zipfile.ZipFile(archive_path, "r") as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name, "r") as raw_stream:
            reader = csv.reader(io.TextIOWrapper(raw_stream, encoding="utf-8", errors="replace"))
            for row in reader:
                if len(row) < 2:
                    continue
                try:
                    rank = int(row[0])
                except ValueError:
                    continue
                domain = row[1].strip().lower()
                parts = domain.split(".")
                # Keep clean 2-part registrable domains (e.g. firma.de, brand.at, shop.ch)
                if len(parts) != 2:
                    continue
                name_part, tld = parts[0], parts[1]
                if tld not in DACH_TLDS:
                    continue
                if len(name_part) < 3 or domain in seen or domain in NON_TARGET_DOMAINS:
                    continue
                if any(sub in name_part for sub in NON_B2B_SUBSTRINGS):
                    continue

                seen.add(domain)
                results.append((domain, tld, rank, normalize_brand_slug(domain)))
                if len(results) >= max_domains:
                    break

    return results


def seed_domains_to_duckdb(
    store: DuckDBStore,
    max_domains: int = 50_000,
) -> dict[str, int]:
    """Download Tranco Top-1M, extract DACH commercial domains, load frontier, and run Entity Resolution."""
    archive = download_tranco_zip()
    domains = extract_dach_commercial_domains(archive, max_domains=max_domains)
    inserted = store.bulk_insert_domains(domains)
    matched = store.link_domains_to_registry()
    logger.info(
        f"Loaded {inserted:,} DACH commercial domains into frontier ({matched:,} pre-linked to Handelsregister)"
    )
    return {"domains_loaded": inserted, "prelinked_to_registry": matched}
