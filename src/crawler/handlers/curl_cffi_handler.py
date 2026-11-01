"""Hybrid Scrapy 2.19 Async DownloadHandler combining Twisted Fast-Path and curl_cffi Chrome TLS JA3/JA4."""

from __future__ import annotations

from typing import Self

from curl_cffi.requests import AsyncSession
from scrapy import Request
from scrapy.core.downloader.handlers.http11 import HTTP11DownloadHandler
from scrapy.crawler import Crawler
from scrapy.http import Headers, HtmlResponse, Response

from config.settings import settings

CHROME_CLIENT_HINT_HEADERS: dict[str, str] = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
}


class HybridAdaptiveDownloadHandler:
    """Routes normal traffic via Scrapy's Twisted HTTP11 pool and escalated traffic via curl_cffi AsyncSession."""

    lazy = False

    def __init__(self, crawler: Crawler) -> None:
        self.crawler = crawler
        self._twisted_handler = HTTP11DownloadHandler.from_crawler(crawler)
        self._impersonate = crawler.settings.get("CURL_CFFI_IMPERSONATE", settings.curl_cffi_impersonate)
        self._force_curl_cffi = crawler.settings.getbool("FORCE_CURL_CFFI", settings.force_curl_cffi)
        self._timeout = crawler.settings.getint("DOWNLOAD_TIMEOUT", settings.download_timeout_seconds)
        self._curl_session: AsyncSession | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> Self:
        return cls(crawler)

    def _get_curl_session(self) -> AsyncSession:
        if self._curl_session is None:
            self._curl_session = AsyncSession(
                impersonate=self._impersonate,
                max_clients=128,
                verify=False,
            )
        return self._curl_session

    async def download_request(self, request: Request) -> Response:
        tier = request.meta.get("transport_tier")
        if self._force_curl_cffi and not tier:
            tier = "curl_cffi"
            request.meta["transport_tier"] = "curl_cffi"

        if tier == "curl_cffi":
            return await self._download_via_curl_cffi(request)

        request.meta.setdefault("transport_tier", "twisted")
        self.crawler.stats.inc_value("transport/twisted_requests")
        return await self._twisted_handler.download_request(request)

    async def _download_via_curl_cffi(self, request: Request) -> Response:
        self.crawler.stats.inc_value("transport/curl_cffi_requests")
        session = self._get_curl_session()

        merged_headers = dict(CHROME_CLIENT_HINT_HEADERS)
        for k, v_list in request.headers.items():
            key_str = k.decode("latin1") if isinstance(k, bytes) else str(k)
            if v_list and key_str.lower() != "user-agent":
                val = v_list[0]
                merged_headers[key_str] = val.decode("latin1") if isinstance(val, bytes) else str(val)

        timeout_sec = float(request.meta.get("download_timeout") or self._timeout)
        c_resp = await session.request(
            method=request.method,
            url=request.url,
            headers=merged_headers,
            data=request.body if request.body else None,
            timeout=timeout_sec,
            allow_redirects=True,
        )

        # libcurl already decompresses gzip/br/zstd payloads into c_resp.content;
        # strip Content-Encoding so Scrapy's HttpCompressionMiddleware does not double-decompress.
        resp_headers = Headers(
            {
                k: v
                for k, v in c_resp.headers.items()
                if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
            }
        )
        content_type = (c_resp.headers.get("content-type") or "").lower()
        final_url = str(c_resp.url or request.url)

        if "html" in content_type or "xml" in content_type or "text" in content_type or not content_type:
            return HtmlResponse(
                url=final_url,
                status=c_resp.status_code,
                headers=resp_headers,
                body=c_resp.content,
                request=request,
                flags=["curl_cffi"],
            )
        return Response(
            url=final_url,
            status=c_resp.status_code,
            headers=resp_headers,
            body=c_resp.content,
            request=request,
            flags=["curl_cffi"],
        )

    async def close(self) -> None:
        if self._curl_session is not None:
            await self._curl_session.close()
            self._curl_session = None
        await self._twisted_handler.close()
