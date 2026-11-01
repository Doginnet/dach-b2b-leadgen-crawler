"""Batched Dual-Mode Item Pipeline flushing B2B leads in chunks of 500 to DuckDB and PostgreSQL."""

from __future__ import annotations

from typing import Any, Self

from loguru import logger
from scrapy.crawler import Crawler

from config.settings import settings
from src.models.lead import EnrichedB2BLead
from src.storage.duckdb_store import DuckDBStore
from src.storage.postgres_store import PostgresStore


class BatchStoragePipeline:
    """Buffers yielded EnrichedB2BLead items in RAM and executes high-speed bulk upserts."""

    def __init__(self, crawler: Crawler) -> None:
        self.crawler = crawler
        self.batch_size = crawler.settings.getint("PIPELINE_BATCH_SIZE", settings.pipeline_batch_size)
        self.storage_mode = crawler.settings.get("STORAGE_MODE", settings.storage_mode)
        self._buffer: list[EnrichedB2BLead] = []
        self._duck_store: DuckDBStore | None = None
        self._pg_store: PostgresStore | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        return cls(crawler)

    def open_spider(self) -> None:
        self._duck_store = DuckDBStore()
        if self.storage_mode == "dual":
            try:
                self._pg_store = PostgresStore()
                self._pg_store.ensure_schema()
                logger.info("BatchStoragePipeline connected to Dual-Mode (PostgreSQL 16 + DuckDB Lakehouse)")
            except Exception as exc:
                logger.warning(f"PostgreSQL unavailable ({exc}); falling back to DuckDB Lakehouse mode")
                self._pg_store = None

    def process_item(self, item: dict[str, Any] | EnrichedB2BLead) -> dict[str, Any]:
        lead = item if isinstance(item, EnrichedB2BLead) else EnrichedB2BLead.model_validate(item)
        self._buffer.append(lead)
        if len(self._buffer) >= self.batch_size:
            self._flush()
        return lead.model_dump(mode="json")

    def close_spider(self) -> None:
        if self._buffer:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer or self._duck_store is None:
            return
        batch = list(self._buffer)
        self._buffer.clear()

        resolved = self._duck_store.resolve_and_enrich_leads(batch)
        written = self._duck_store.upsert_leads(resolved)
        self.crawler.stats.inc_value("storage/duckdb_upserted", written)

        if self._pg_store is not None:
            try:
                pg_written = self._pg_store.upsert_leads(resolved)
                self.crawler.stats.inc_value("storage/postgres_upserted", pg_written)
            except Exception as exc:
                logger.error(f"PostgreSQL batch upsert failed: {exc}")
