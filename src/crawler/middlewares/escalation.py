"""Adaptive Anti-Bot Escalation Middleware: Twisted Fast-Path -> curl_cffi Chrome TLS -> Optional Browser."""

from __future__ import annotations

from typing import Self

from loguru import logger
from scrapy import Request
from scrapy.crawler import Crawler
from scrapy.http import Response

WAF_STATUS_CODES = {403, 406, 429, 503}
WAF_BODY_SIGNATURES = (
    b"Attention Required! | Cloudflare",
    b"Just a moment...",
    b"cf-browser-verification",
    b"__cf_chl_opt",
    b"ddos-guard",
    b"Access Denied",
    b"Enable JavaScript and cookies to continue",
)


class AntiBotEscalationMiddleware:
    """Detects WAF/TLS blocks on Twisted requests and transparently retries via curl_cffi Chrome 124 TLS."""

    def __init__(self, crawler: Crawler) -> None:
        self.crawler = crawler
        self.enable_browser = crawler.settings.getbool("ENABLE_BROWSER_FALLBACK", False)

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        return cls(crawler)

    @staticmethod
    def _looks_like_waf_challenge(response: Response) -> bool:
        if response.status in WAF_STATUS_CODES:
            return True
        server_hdr = (response.headers.get(b"Server") or b"").lower()
        if b"cloudflare" in server_hdr and response.status >= 400:
            return True
        if len(response.body) < 18_000:
            head_slice = response.body[:8192]
            if any(sig in head_slice for sig in WAF_BODY_SIGNATURES):
                return True
        return False

    def process_response(self, request: Request, response: Response) -> Response | Request:
        current_tier = request.meta.get("transport_tier", "twisted")
        already_escalated = bool(request.meta.get("_escalated_curl_cffi"))

        if current_tier == "twisted" and not already_escalated and self._looks_like_waf_challenge(response):
            self.crawler.stats.inc_value("antibot/escalated_to_curl_cffi")
            logger.debug(
                f"[WAF Escalation] HTTP {response.status} on {request.url} (Twisted) -> Retrying with curl_cffi Chrome124"
            )
            escalated_req = request.replace(dont_filter=True)
            escalated_req.meta["transport_tier"] = "curl_cffi"
            escalated_req.meta["_escalated_curl_cffi"] = True
            return escalated_req

        return response

    def process_exception(self, request: Request, exception: Exception) -> Request | None:
        current_tier = request.meta.get("transport_tier", "twisted")
        already_escalated = bool(request.meta.get("_escalated_curl_cffi"))

        # Retry TLS handshake / OpenSSL rejections on Twisted using BoringSSL/Chrome TLS via curl_cffi
        if current_tier == "twisted" and not already_escalated:
            exc_name = type(exception).__name__.lower()
            if any(tok in exc_name for tok in ("ssl", "tls", "connect", "response", "timeout")):
                self.crawler.stats.inc_value("antibot/exception_escalated_to_curl_cffi")
                escalated_req = request.replace(dont_filter=True)
                escalated_req.meta["transport_tier"] = "curl_cffi"
                escalated_req.meta["_escalated_curl_cffi"] = True
                return escalated_req

        return None
