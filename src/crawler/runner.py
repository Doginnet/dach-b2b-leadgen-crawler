"""Scrapy engine configuration and programmatic CrawlerProcess runner."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from config.settings import settings
from src.crawler.spiders.dach_lead_spider import DachLeadSpider, DachRedisLeadSpider


def build_scrapy_settings(
    concurrent_requests: int | None = None,
    use_redis: bool | None = None,
    force_curl_cffi: bool | None = None,
    log_level: str = "WARNING",
) -> Settings:
    """Construct production Scrapy 2.19 settings with HybridAdaptiveDownloadHandler and escalation middleware."""
    redis_enabled = settings.use_redis_frontier if use_redis is None else use_redis
    force_cffi = settings.force_curl_cffi if force_curl_cffi is None else force_curl_cffi

    cfg: dict[str, Any] = {
        "BOT_NAME": "dach_b2b_leadgen",
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "ROBOTSTXT_OBEY": False,
        "COOKIES_ENABLED": True,
        "REDIRECT_ENABLED": True,
        "REDIRECT_MAX_TIMES": 4,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "DOWNLOAD_TIMEOUT": settings.download_timeout_seconds,
        "DOWNLOAD_MAXSIZE": 4 * 1024 * 1024,  # Cap at 4 MB per HTML page to protect worker RAM
        "CONCURRENT_REQUESTS": concurrent_requests or settings.concurrent_requests,
        "CONCURRENT_REQUESTS_PER_DOMAIN": settings.concurrent_requests_per_domain,
        "REACTOR_THREADPOOL_MAXSIZE": 32,
        "DNS_TIMEOUT": 10,
        "LOG_LEVEL": log_level,
        "CURL_CFFI_IMPERSONATE": settings.curl_cffi_impersonate,
        "FORCE_CURL_CFFI": force_cffi,
        "ENABLE_BROWSER_FALLBACK": settings.enable_browser_fallback,
        "STORAGE_MODE": settings.storage_mode,
        "PIPELINE_BATCH_SIZE": settings.pipeline_batch_size,
        "DOWNLOAD_HANDLERS": {
            "http": "src.crawler.handlers.curl_cffi_handler.HybridAdaptiveDownloadHandler",
            "https": "src.crawler.handlers.curl_cffi_handler.HybridAdaptiveDownloadHandler",
        },
        "DOWNLOADER_MIDDLEWARES": {
            "src.crawler.middlewares.escalation.AntiBotEscalationMiddleware": 560,
        },
        "ITEM_PIPELINES": {
            "src.crawler.pipelines.storage_pipeline.BatchStoragePipeline": 300,
        },
    }

    if redis_enabled:
        cfg.update(
            {
                "SCHEDULER": "scrapy_redis.scheduler.Scheduler",
                "DUPEFILTER_CLASS": "scrapy_redis.dupefilter.RFPDupeFilter",
                "SCHEDULER_PERSIST": True,
                "REDIS_URL": settings.redis_url,
            }
        )

    s = Settings()
    s.setdict(cfg, priority="project")
    return s


def run_crawl_process(
    limit: int = 100,
    domains: list[str] | None = None,
    concurrent_requests: int | None = None,
    use_redis: bool = False,
    force_curl_cffi: bool = False,
    log_level: str = "INFO",
) -> dict[str, Any]:
    """Run Scrapy CrawlerProcess synchronously (in dedicated CLI or worker process) and return stats."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    scrapy_settings = build_scrapy_settings(
        concurrent_requests=concurrent_requests,
        use_redis=use_redis,
        force_curl_cffi=force_curl_cffi,
        log_level=log_level,
    )
    process = CrawlerProcess(settings=scrapy_settings)

    if use_redis:
        crawler = process.create_crawler(DachRedisLeadSpider)
        process.crawl(crawler)
    else:
        crawler = process.create_crawler(DachLeadSpider)
        process.crawl(crawler, limit=limit, domains=domains)

    process.start()
    return dict(crawler.stats.get_stats())
