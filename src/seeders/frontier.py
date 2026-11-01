"""Distributed Redis URL frontier feeder (scrapy-redis) with DuckDB standalone fallback."""

from __future__ import annotations

import json
from typing import Any

import redis
from loguru import logger

from config.settings import settings
from src.storage.duckdb_store import DuckDBStore


def push_frontier_to_redis(
    store: DuckDBStore,
    limit: int = 1000,
    redis_url: str | None = None,
    redis_key: str | None = None,
) -> int:
    """Enqueue pending DACH domains from DuckDB lakehouse into Redis for multi-worker Scrapy cluster."""
    targets = store.fetch_pending_domains(limit=limit, prefer_matched=True)
    if not targets:
        return 0

    r_url = redis_url or settings.redis_url
    key = redis_key or settings.redis_start_urls_key
    client = redis.Redis.from_url(r_url, decode_responses=True)

    pipe = client.pipeline(transaction=False)
    for item in targets:
        payload = json.dumps(
            {
                "url": f"https://{item['domain']}/",
                "meta": {
                    "domain": item["domain"],
                    "tld": item["tld"],
                    "tranco_rank": item["tranco_rank"],
                    "company_number": item["matched_company_number"],
                },
            }
        )
        pipe.rpush(key, payload)
    pipe.execute()
    logger.info(f"Enqueued {len(targets):,} target domains into Redis list '{key}'")
    return len(targets)


def get_redis_queue_status(redis_url: str | None = None, redis_key: str | None = None) -> dict[str, Any]:
    """Non-blocking Redis queue health & backlog check for the FastAPI Cluster Monitor."""
    r_url = redis_url or settings.redis_url
    key = redis_key or settings.redis_start_urls_key
    try:
        client = redis.Redis.from_url(r_url, socket_connect_timeout=0.5, socket_timeout=0.5, decode_responses=True)
        client.ping()
        queued = int(client.llen(key))
        dupefilter_size = int(client.scard("dach_leadgen:dupefilter") or 0)
        return {
            "connected": True,
            "redis_key": key,
            "queued_urls": queued,
            "seen_fingerprints": dupefilter_size,
        }
    except Exception:
        return {
            "connected": False,
            "redis_key": key,
            "queued_urls": 0,
            "seen_fingerprints": 0,
        }
