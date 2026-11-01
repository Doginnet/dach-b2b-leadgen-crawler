"""Offline deterministic unit tests for extractors, scoring, DuckDB OLAP, anti-bot escalation, FastAPI, and n8n."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scrapy import Request, Spider
from scrapy.http import HtmlResponse
from scrapy.utils.test import get_crawler

from config.settings import PROJECT_ROOT
from src.crawler.middlewares.escalation import AntiBotEscalationMiddleware
from src.extractors.adtech import AdTechFingerprinter
from src.extractors.impressum import ImpressumExtractor
from src.extractors.scoring import LeadScorer
from src.models.lead import EnrichedB2BLead
from src.seeders.offeneregister import parse_offeneregister_record
from src.storage.duckdb_store import DuckDBStore
from src.web.api import create_app

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class DummySpider(Spider):
    name = "dummy_unit_spider"


@pytest.mark.unit
def test_adtech_fingerprinter_signatures_and_merge() -> None:
    homepage_html = (FIXTURES_DIR / "sample_shopware_homepage.html").read_text(encoding="utf-8")
    profile = AdTechFingerprinter.analyze(homepage_html)

    assert profile.is_ecommerce is True
    assert profile.primary_cms == "Shopware"
    assert profile.has_google_ads is True
    assert profile.has_gtm is True
    assert profile.has_ga4 is True
    assert profile.has_meta_pixel is False
    assert profile.has_tiktok_pixel is False
    assert profile.primary_cmp == "Usercentrics"

    # Merge subpage carrying Klaviyo & LinkedIn Insight Tag
    sub_html = """
    <script src="https://static.klaviyo.com/onsite/js/klaviyo.js?company_id=XY12"></script>
    <script src="https://snap.licdn.com/li.lms-analytics/insight.min.js"></script>
    """
    merged = AdTechFingerprinter.merge(profile, AdTechFingerprinter.analyze(sub_html))
    assert merged.primary_cms == "Shopware"
    assert merged.primary_crm == "Klaviyo"
    assert merged.has_linkedin_pixel is True
    assert merged.has_google_ads is True


@pytest.mark.unit
def test_impressum_extractor_ddg_and_deobfuscation() -> None:
    homepage_html = (FIXTURES_DIR / "sample_shopware_homepage.html").read_text(encoding="utf-8")
    impressum_html = (FIXTURES_DIR / "sample_impressum.html").read_text(encoding="utf-8")

    links = ImpressumExtractor.discover_target_links(homepage_html, "https://alpentechnik-shop.de/")
    assert links[0] == "https://alpentechnik-shop.de/impressum"
    assert "https://alpentechnik-shop.de/kontakt" in links

    home_contacts = ImpressumExtractor.extract(homepage_html)
    imp_contacts = ImpressumExtractor.extract(impressum_html)
    merged = ImpressumExtractor.merge(imp_contacts, home_contacts)

    assert merged.legal_name == "AlpenTechnik Commerce GmbH"
    assert merged.legal_form == "GmbH"
    assert "Dr. Lukas Weber" in merged.ceo_names
    assert "Katharina Becker" in merged.ceo_names
    # Leadership email prioritized ahead of info@ and datenschutz@; sentry.io & @2x.png rejected
    assert merged.primary_email == "l.weber@alpentechnik-shop.de"
    assert "info@alpentechnik-shop.de" in merged.emails
    assert not any("sentry.io" in e or ".png" in e for e in merged.emails)
    assert merged.vat_id == "DE319482710"
    assert merged.register_type == "HRB"
    assert merged.register_id == "248910"
    assert merged.register_court == "Amtsgericht München"
    assert merged.postal_code == "80802"
    assert merged.city == "München"
    assert "linkedin" in merged.social_links
    assert "instagram" in merged.social_links


@pytest.mark.unit
def test_lead_scorer_ad_spend_gap_segments() -> None:
    homepage_html = (FIXTURES_DIR / "sample_shopware_homepage.html").read_text(encoding="utf-8")
    impressum_html = (FIXTURES_DIR / "sample_impressum.html").read_text(encoding="utf-8")

    adtech = AdTechFingerprinter.analyze(homepage_html)
    contacts = ImpressumExtractor.extract(impressum_html)
    result = LeadScorer.score(contacts=contacts, adtech=adtech, registry_matched=True)

    assert result.pitch_segment == "PAID_SEARCH_MISSING_SOCIAL"
    assert result.lead_score >= 85
    assert "Google Ads" in result.pitch_angle


@pytest.mark.unit
def test_offeneregister_and_duckdb_entity_resolution(tmp_path: Path) -> None:
    raw_record = {
        "company_number": "D2601V_HRB248910",
        "current_status": "currently registered",
        "name": "AlpenTechnik Commerce GmbH",
        "registered_address": "Leopoldstraße 48, 80802 München.",
        "all_attributes": {
            "_registerArt": "HRB",
            "_registerNummer": "248910",
            "federal_state": "Bayern",
            "native_company_number": "München HRB 248910",
            "registered_office": "München",
        },
        "officers": [
            {"name": "Dr. Lukas Weber", "position": "Geschäftsführer"},
            {"name": "Markus Steiner", "position": "Geschäftsführer"},
        ],
    }
    entity = parse_offeneregister_record(raw_record)
    assert entity is not None
    assert entity.register_type == "HRB"
    assert entity.register_id == "248910"
    assert entity.federal_state == "Bayern"

    db_file = tmp_path / "unit_lakehouse.duckdb"
    empty_showcase = tmp_path / "nonexistent.parquet"
    store = DuckDBStore(db_path=db_file, showcase_parquet=empty_showcase)
    assert store.bulk_insert_registry_arrow([entity]) == 1

    store.bulk_insert_domains([("alpentechnik.de", "de", 4500, entity.brand_slug)])
    linked = store.link_domains_to_registry()
    assert linked == 1

    # Upsert crawled lead carrying HRB 248910 -> should inherit Bayern + Markus Steiner officer from registry
    crawled_lead = EnrichedB2BLead(
        domain="alpentechnik-shop.de",
        tld="de",
        email="l.weber@alpentechnik-shop.de",
        all_emails=["l.weber@alpentechnik-shop.de"],
        ceo_name="Dr. Lukas Weber",
        all_ceos=["Dr. Lukas Weber"],
        register_code="HRB 248910",
        register_court="Amtsgericht München",
        primary_cms="Shopware",
        is_ecommerce=True,
        has_google_ads=True,
        ad_pixels=["Google Ads"],
        lead_score=80,
        pitch_segment="PAID_SEARCH_MISSING_SOCIAL",
    )
    store.upsert_leads([crawled_lead])

    res = store.query_leads(require_pixel="google_ads", missing_pixel="meta")
    assert res["total"] == 1
    row = res["items"][0]
    assert row["company_number"] == "D2601V_HRB248910"
    assert row["federal_state"] == "Bayern"
    assert row["lead_score"] >= 85


@pytest.mark.unit
def test_antibot_escalation_middleware_prevents_loops() -> None:
    crawler = get_crawler(DummySpider)
    mw = AntiBotEscalationMiddleware.from_crawler(crawler)

    req = Request("https://protected-shop.de/", meta={"transport_tier": "twisted"})
    cf_resp = HtmlResponse(
        url="https://protected-shop.de/",
        status=403,
        headers={b"Server": b"cloudflare"},
        body=b"<html><title>Just a moment...</title></html>",
        request=req,
    )

    escalated = mw.process_response(req, cf_resp)
    assert isinstance(escalated, Request)
    assert escalated.meta["transport_tier"] == "curl_cffi"
    assert escalated.meta["_escalated_curl_cffi"] is True
    assert crawler.stats.get_value("antibot/escalated_to_curl_cffi") == 1

    # Second 403 after curl_cffi escalation must return Response directly without infinite loop
    second_resp = HtmlResponse(
        url="https://protected-shop.de/",
        status=403,
        body=b"Blocked",
        request=escalated,
    )
    final_out = mw.process_response(escalated, second_resp)
    assert final_out is second_resp


@pytest.mark.unit
def test_fastapi_endpoints_and_n8n_mark_exported(tmp_path: Path) -> None:
    db_file = tmp_path / "api_test.duckdb"
    store = DuckDBStore(db_path=db_file, showcase_parquet=tmp_path / "none.parquet")
    store.upsert_leads(
        [
            EnrichedB2BLead(
                domain="hot-shopware-lead.de",
                tld="de",
                legal_name="Hot Shopware GmbH",
                legal_form="GmbH",
                city="Berlin",
                federal_state="Berlin",
                ceo_name="Anna Schmidt",
                all_ceos=["Anna Schmidt"],
                email="a.schmidt@hot-shopware-lead.de",
                all_emails=["a.schmidt@hot-shopware-lead.de"],
                vat_id="DE123456789",
                register_code="HRB 998877",
                primary_cms="Shopware",
                is_ecommerce=True,
                has_google_ads=True,
                has_meta_pixel=False,
                ad_pixels=["Google Ads"],
                lead_score=92,
                pitch_segment="PAID_SEARCH_MISSING_SOCIAL",
                pitch_angle="Runs Google Ads on Shopware, missing Meta Pixel.",
            )
        ]
    )

    app = create_app(db_path=db_file)
    client = TestClient(app)

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/").status_code == 200

    stats_resp = client.get("/api/v1/stats")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["leads"]["hot_leads"] == 1

    csv_resp = client.get("/api/v1/export/csv?min_score=75")
    assert csv_resp.status_code == 200
    assert "hot-shopware-lead.de" in csv_resp.text

    n8n_resp = client.get("/api/v1/n8n/hot-leads?min_score=75")
    assert n8n_resp.status_code == 200
    n8n_data = n8n_resp.json()
    assert n8n_data["count"] == 1
    assert "Hallo Anna Schmidt," in n8n_data["leads"][0]["outreach_draft"]["body_de"]

    ack_resp = client.post("/api/v1/n8n/mark-exported", json={"domains": ["hot-shopware-lead.de"]})
    assert ack_resp.status_code == 200
    assert ack_resp.json()["updated"] == 1

    # Verify idempotency: exported lead is no longer returned to n8n
    assert client.get("/api/v1/n8n/hot-leads?min_score=75").json()["count"] == 0


@pytest.mark.unit
def test_n8n_workflow_json_contract() -> None:
    wf_path = PROJECT_ROOT / "workflows" / "n8n_b2b_lead_router.json"
    assert wf_path.exists()
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    assert len(wf["nodes"]) == 9
    node_names = {n["name"] for n in wf["nodes"]}
    for src_node, targets in wf["connections"].items():
        assert src_node in node_names
        for branch in targets.get("main", []):
            for edge in branch:
                assert edge["node"] in node_names
