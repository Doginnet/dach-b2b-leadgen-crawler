"""Distributed & Standalone DACH B2B LeadGen Spiders: Homepage -> /impressum & /kontakt (max 3 pages/domain)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import scrapy
from scrapy import Request
from scrapy.http import Response
from scrapy_redis.spiders import RedisSpider

from config.settings import settings
from src.extractors.adtech import AdTechFingerprinter
from src.extractors.impressum import IMPRESSUM_LINK_RE, ImpressumExtractor
from src.extractors.scoring import LeadScorer
from src.models.lead import AdTechProfile, EnrichedB2BLead, ImpressumContacts
from src.storage.duckdb_store import DuckDBStore


class DachLeadExtractionMixin:
    """Shared extraction workflow across standalone DachLeadSpider and distributed DachRedisLeadSpider."""

    max_subpages: int = max(0, settings.max_pages_per_domain - 1)

    @staticmethod
    def _decode_html(response: Response) -> str:
        try:
            return response.text
        except Exception:
            return response.body.decode("utf-8", errors="replace")

    @staticmethod
    def _headers_blob(response: Response) -> str:
        lines: list[str] = []
        for k, vals in response.headers.items():
            k_str = k.decode("latin1", errors="ignore")
            v_str = b"; ".join(vals).decode("latin1", errors="ignore")
            lines.append(f"{k_str}: {v_str}")
        return "\n".join(lines)

    def parse_homepage(self, response: Response) -> Iterator[Request | dict[str, Any]]:
        domain = str(response.meta.get("domain") or "").strip().lower()
        tld = str(response.meta.get("tld") or domain.rsplit(".", 1)[-1]).lower()
        tranco_rank = response.meta.get("tranco_rank")
        company_number = str(response.meta.get("company_number") or "")
        transport_tier = str(response.meta.get("transport_tier") or "twisted")

        if response.status >= 400 or not response.body:
            return

        html = self._decode_html(response)
        adtech = AdTechFingerprinter.analyze(html, self._headers_blob(response))
        contacts = ImpressumExtractor.extract(html)
        title = ImpressumExtractor.extract_title(html)

        subpages = ImpressumExtractor.discover_target_links(
            html=html,
            base_url=response.url,
            max_links=self.max_subpages,
        )

        state: dict[str, Any] = {
            "domain": domain,
            "tld": tld,
            "tranco_rank": tranco_rank,
            "company_number": company_number,
            "site_title": title,
            "http_status": response.status,
            "transport_tier": transport_tier,
            "pages_crawled": 1,
            "impressum_url": "",
            "adtech": adtech.model_dump(),
            "contacts": contacts.model_dump(),
        }

        if not subpages:
            yield self._finalize_lead(state)
            return

        next_url = subpages[0]
        state["remaining_urls"] = subpages[1:]
        if IMPRESSUM_LINK_RE.search(next_url):
            state["impressum_url"] = next_url

        yield Request(
            url=next_url,
            callback=self.parse_subpage,
            errback=self.handle_subpage_error,
            dont_filter=True,
            meta={
                "domain": domain,
                "transport_tier": transport_tier,
                "lead_state": state,
                "download_timeout": settings.download_timeout_seconds,
            },
        )

    def parse_subpage(self, response: Response) -> Iterator[Request | dict[str, Any]]:
        state: dict[str, Any] = dict(response.meta["lead_state"])
        if response.meta.get("transport_tier") == "curl_cffi":
            state["transport_tier"] = "curl_cffi"

        if 200 <= response.status < 400 and response.body:
            state["pages_crawled"] = int(state.get("pages_crawled", 1)) + 1
            html = self._decode_html(response)
            sub_adtech = AdTechFingerprinter.analyze(html, self._headers_blob(response))
            sub_contacts = ImpressumExtractor.extract(html)

            prev_adtech = AdTechProfile.model_validate(state["adtech"])
            prev_contacts = ImpressumContacts.model_validate(state["contacts"])

            merged_adtech = AdTechFingerprinter.merge(prev_adtech, sub_adtech)
            # Impressum page legal fields take priority over generic homepage footer snippets
            if IMPRESSUM_LINK_RE.search(response.url):
                state["impressum_url"] = response.url
                merged_contacts = ImpressumExtractor.merge(sub_contacts, prev_contacts)
            else:
                merged_contacts = ImpressumExtractor.merge(prev_contacts, sub_contacts)

            state["adtech"] = merged_adtech.model_dump()
            state["contacts"] = merged_contacts.model_dump()

        remaining: list[str] = list(state.get("remaining_urls") or [])
        if remaining:
            next_url = remaining[0]
            state["remaining_urls"] = remaining[1:]
            if not state["impressum_url"] and IMPRESSUM_LINK_RE.search(next_url):
                state["impressum_url"] = next_url
            yield Request(
                url=next_url,
                callback=self.parse_subpage,
                errback=self.handle_subpage_error,
                dont_filter=True,
                meta={
                    "domain": state["domain"],
                    "transport_tier": state["transport_tier"],
                    "lead_state": state,
                    "download_timeout": settings.download_timeout_seconds,
                },
            )
            return

        yield self._finalize_lead(state)

    def handle_subpage_error(self, failure: Any) -> Iterator[dict[str, Any]]:
        request: Request = failure.request
        state = request.meta.get("lead_state")
        if state:
            yield self._finalize_lead(state)

    @staticmethod
    def _finalize_lead(state: dict[str, Any]) -> dict[str, Any]:
        adtech = AdTechProfile.model_validate(state["adtech"])
        contacts = ImpressumContacts.model_validate(state["contacts"])
        pre_matched = bool(state.get("company_number"))
        score_res = LeadScorer.score(contacts=contacts, adtech=adtech, registry_matched=pre_matched)

        reg_code = (
            f"{contacts.register_type} {contacts.register_id}".strip()
            if contacts.register_type and contacts.register_id
            else ""
        )
        tech_stack = list(
            dict.fromkeys([*adtech.cms_ecommerce, *adtech.crm_marketing, *adtech.consent_cmp])
        )

        lead = EnrichedB2BLead(
            domain=state["domain"],
            tld=state["tld"],
            tranco_rank=state.get("tranco_rank"),
            company_number=state.get("company_number") or "",
            legal_name=contacts.legal_name,
            legal_form=contacts.legal_form,
            city=contacts.city,
            postal_code=contacts.postal_code,
            ceo_name=contacts.ceo_names[0] if contacts.ceo_names else "",
            all_ceos=contacts.ceo_names,
            email=contacts.primary_email,
            all_emails=contacts.emails,
            phone=contacts.primary_phone,
            vat_id=contacts.vat_id,
            register_code=reg_code,
            register_court=contacts.register_court,
            primary_cms=adtech.primary_cms,
            primary_crm=adtech.primary_crm,
            consent_cmp=adtech.primary_cmp,
            is_ecommerce=adtech.is_ecommerce,
            has_meta_pixel=adtech.has_meta_pixel,
            has_google_ads=adtech.has_google_ads,
            has_gtm=adtech.has_gtm,
            has_ga4=adtech.has_ga4,
            has_tiktok_pixel=adtech.has_tiktok_pixel,
            has_linkedin_pixel=adtech.has_linkedin_pixel,
            has_pinterest_pixel=adtech.has_pinterest_pixel,
            has_microsoft_uet=adtech.has_microsoft_uet,
            ad_pixels=adtech.ad_pixels,
            tech_stack=tech_stack,
            instagram_url=contacts.social_links.get("instagram", ""),
            linkedin_url=contacts.social_links.get("linkedin", ""),
            tiktok_url=contacts.social_links.get("tiktok", ""),
            facebook_url=contacts.social_links.get("facebook", ""),
            lead_score=score_res.lead_score,
            pitch_segment=score_res.pitch_segment,
            pitch_angle=score_res.pitch_angle,
            transport_tier=state.get("transport_tier") or "twisted",
            pages_crawled=int(state.get("pages_crawled") or 1),
            impressum_url=state.get("impressum_url") or "",
            site_title=state.get("site_title") or "",
            http_status=int(state.get("http_status") or 200),
        )
        return lead.model_dump(mode="json")


class DachLeadSpider(DachLeadExtractionMixin, scrapy.Spider):
    """Standalone high-concurrency spider pulling targets from DuckDB frontier or explicit domain list."""

    name = "dach_leads"

    def __init__(
        self,
        limit: int = 100,
        domains: list[str] | str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.crawl_limit = int(limit)
        if isinstance(domains, str) and domains.strip():
            self.explicit_domains = [d.strip().lower() for d in domains.split(",") if d.strip()]
        elif isinstance(domains, list):
            self.explicit_domains = [d.strip().lower() for d in domains if d.strip()]
        else:
            self.explicit_domains = []

    def _build_initial_requests(self) -> list[Request]:
        requests_out: list[Request] = []
        if self.explicit_domains:
            for dom in self.explicit_domains[: self.crawl_limit]:
                clean_dom = dom.split("://")[-1].split("/")[0]
                if clean_dom.startswith("www."):
                    clean_dom = clean_dom[4:]
                tld = clean_dom.rsplit(".", 1)[-1]
                requests_out.append(
                    Request(
                        url=f"https://{clean_dom}/",
                        callback=self.parse_homepage,
                        dont_filter=True,
                        meta={
                            "domain": clean_dom,
                            "tld": tld,
                            "tranco_rank": None,
                            "company_number": "",
                            "download_timeout": settings.download_timeout_seconds,
                        },
                    )
                )
            return requests_out

        store = DuckDBStore()
        targets = store.fetch_pending_domains(limit=self.crawl_limit, prefer_matched=True)
        for item in targets:
            dom = item["domain"]
            requests_out.append(
                Request(
                    url=f"https://{dom}/",
                    callback=self.parse_homepage,
                    dont_filter=True,
                    meta={
                        "domain": dom,
                        "tld": item["tld"],
                        "tranco_rank": item["tranco_rank"],
                        "company_number": item["matched_company_number"],
                        "download_timeout": settings.download_timeout_seconds,
                    },
                )
            )
        return requests_out

    async def start(self) -> AsyncIterator[Request]:
        for req in self._build_initial_requests():
            yield req


class DachRedisLeadSpider(DachLeadExtractionMixin, RedisSpider):
    """Distributed multi-worker spider consuming target domains atomically from Redis (scrapy-redis)."""

    name = "dach_leads_redis"
    redis_key = settings.redis_start_urls_key

    def make_request_from_data(self, data: bytes) -> Request:
        raw_str = data.decode("utf-8", errors="replace").strip()
        if raw_str.startswith("{"):
            payload = json.loads(raw_str)
            url = payload["url"]
            meta = dict(payload.get("meta") or {})
        else:
            clean_dom = raw_str.split("://")[-1].split("/")[0].lower()
            if clean_dom.startswith("www."):
                clean_dom = clean_dom[4:]
            url = f"https://{clean_dom}/"
            meta = {"domain": clean_dom, "tld": clean_dom.rsplit(".", 1)[-1]}

        meta.setdefault("download_timeout", settings.download_timeout_seconds)
        return Request(url=url, callback=self.parse_homepage, dont_filter=True, meta=meta)
