"""Unified application settings powered by Pydantic Settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """Centralized settings across Seeder, Scrapy Crawler, Dual-Mode Storage, FastAPI, and n8n."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Execution & Storage Mode
    storage_mode: Literal["duckdb", "dual"] = Field(
        default="duckdb",
        description="duckdb for standalone OLAP/Parquet mode; dual for PostgreSQL + DuckDB/Parquet cluster mode",
    )
    duckdb_path: Path = Field(default=PROJECT_ROOT / "data" / "lakehouse" / "dach_leads.duckdb")
    parquet_export_path: Path = Field(default=PROJECT_ROOT / "data" / "lakehouse" / "companies_1m.parquet")
    showcase_parquet_path: Path = Field(default=PROJECT_ROOT / "data" / "samples" / "leads_showcase.parquet")
    showcase_csv_path: Path = Field(default=PROJECT_ROOT / "data" / "samples" / "leads_showcase.csv")
    cache_dir: Path = Field(default=PROJECT_ROOT / "data" / "cache")

    # 2. Distributed Cluster Infrastructure (Docker Compose / scrapy-redis / PostgreSQL)
    use_redis_frontier: bool = Field(default=False)
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_start_urls_key: str = Field(default="dach_leadgen:start_urls")

    postgres_dsn: str = Field(default="postgresql://leadgen:leadgen_secret@localhost:5432/dach_leads")
    pipeline_batch_size: int = Field(default=500, ge=10, le=10000)

    # 3. Scrapy Concurrency & Adaptive Anti-Bot Escalation
    concurrent_requests: int = Field(default=64, ge=1, le=512)
    concurrent_requests_per_domain: int = Field(default=2, ge=1, le=16)
    download_timeout_seconds: int = Field(default=10, ge=3, le=60)
    max_pages_per_domain: int = Field(default=3, ge=1, le=10)

    curl_cffi_impersonate: str = Field(default="chrome124")
    force_curl_cffi: bool = Field(default=False)
    enable_browser_fallback: bool = Field(default=False)

    # 4. Seeding & Lead Scoring Thresholds
    offeneregister_dump_url: str = Field(
        default="https://daten.offeneregister.de/de_companies_ocdata.jsonl.bz2"
    )
    tranco_top_1m_url: str = Field(default="https://tranco-list.eu/top-1m.csv.zip")
    default_seed_rows: int = Field(default=1_000_000, ge=100)
    hot_lead_score_threshold: int = Field(default=75, ge=0, le=100)

    # 5. FastAPI Lead Explorer & n8n Integration
    web_host: str = Field(default="127.0.0.1")
    web_port: int = Field(default=8765, ge=1024, le=65535)
    n8n_webhook_url: str = Field(default="")


settings = AppSettings()
