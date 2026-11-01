"""Standard Scrapy settings module for `scrapy crawl dach_leads` / `scrapy crawl dach_leads_redis`."""

from __future__ import annotations

import asyncio
import sys

from config.settings import settings

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BOT_NAME = "dach_b2b_leadgen"
SPIDER_MODULES = ["src.crawler.spiders"]
NEWSPIDER_MODULE = "src.crawler.spiders"

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ROBOTSTXT_OBEY = False
COOKIES_ENABLED = True
REDIRECT_ENABLED = True
REDIRECT_MAX_TIMES = 4
RETRY_ENABLED = True
RETRY_TIMES = 1
DOWNLOAD_TIMEOUT = settings.download_timeout_seconds
DOWNLOAD_MAXSIZE = 4 * 1024 * 1024

CONCURRENT_REQUESTS = settings.concurrent_requests
CONCURRENT_REQUESTS_PER_DOMAIN = settings.concurrent_requests_per_domain
REACTOR_THREADPOOL_MAXSIZE = 32
DNS_TIMEOUT = 10
LOG_LEVEL = "INFO"

CURL_CFFI_IMPERSONATE = settings.curl_cffi_impersonate
FORCE_CURL_CFFI = settings.force_curl_cffi
ENABLE_BROWSER_FALLBACK = settings.enable_browser_fallback
STORAGE_MODE = settings.storage_mode
PIPELINE_BATCH_SIZE = settings.pipeline_batch_size

DOWNLOAD_HANDLERS = {
    "http": "src.crawler.handlers.curl_cffi_handler.HybridAdaptiveDownloadHandler",
    "https": "src.crawler.handlers.curl_cffi_handler.HybridAdaptiveDownloadHandler",
}

DOWNLOADER_MIDDLEWARES = {
    "src.crawler.middlewares.escalation.AntiBotEscalationMiddleware": 560,
}

ITEM_PIPELINES = {
    "src.crawler.pipelines.storage_pipeline.BatchStoragePipeline": 300,
}

if settings.use_redis_frontier:
    SCHEDULER = "scrapy_redis.scheduler.Scheduler"
    DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
    SCHEDULER_PERSIST = True
    REDIS_URL = settings.redis_url
