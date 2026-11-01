"""PostgreSQL 16 OLTP batch upsert store for multi-worker Docker Compose Scrapy clusters."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from config.settings import settings
from src.models.lead import EnrichedB2BLead


class PostgresStore:
    """Concurrent multi-worker OLTP writer using psycopg3 batched INSERT ... ON CONFLICT."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres_dsn

    def ensure_schema(self) -> None:
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS b2b_leads (
                    domain TEXT PRIMARY KEY,
                    tld TEXT NOT NULL,
                    tranco_rank INTEGER,
                    company_number TEXT,
                    legal_name TEXT,
                    legal_form TEXT,
                    federal_state TEXT,
                    city TEXT,
                    postal_code TEXT,
                    ceo_name TEXT,
                    all_ceos JSONB DEFAULT '[]'::jsonb,
                    email TEXT,
                    all_emails JSONB DEFAULT '[]'::jsonb,
                    phone TEXT,
                    vat_id TEXT,
                    register_code TEXT,
                    register_court TEXT,
                    primary_cms TEXT,
                    primary_crm TEXT,
                    consent_cmp TEXT,
                    is_ecommerce BOOLEAN DEFAULT FALSE,
                    has_meta_pixel BOOLEAN DEFAULT FALSE,
                    has_google_ads BOOLEAN DEFAULT FALSE,
                    has_gtm BOOLEAN DEFAULT FALSE,
                    has_ga4 BOOLEAN DEFAULT FALSE,
                    has_tiktok_pixel BOOLEAN DEFAULT FALSE,
                    has_linkedin_pixel BOOLEAN DEFAULT FALSE,
                    has_pinterest_pixel BOOLEAN DEFAULT FALSE,
                    has_microsoft_uet BOOLEAN DEFAULT FALSE,
                    ad_pixels JSONB DEFAULT '[]'::jsonb,
                    tech_stack JSONB DEFAULT '[]'::jsonb,
                    instagram_url TEXT,
                    linkedin_url TEXT,
                    tiktok_url TEXT,
                    facebook_url TEXT,
                    lead_score INTEGER NOT NULL DEFAULT 0,
                    pitch_segment TEXT NOT NULL,
                    pitch_angle TEXT,
                    transport_tier TEXT,
                    pages_crawled INTEGER DEFAULT 1,
                    impressum_url TEXT,
                    site_title TEXT,
                    http_status INTEGER DEFAULT 200,
                    exported_to_crm BOOLEAN DEFAULT FALSE,
                    crawled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_b2b_leads_score ON b2b_leads (lead_score DESC);
                CREATE INDEX IF NOT EXISTS idx_b2b_leads_segment ON b2b_leads (pitch_segment);
                CREATE INDEX IF NOT EXISTS idx_b2b_leads_n8n ON b2b_leads (exported_to_crm, lead_score DESC);
                """
            )
            conn.commit()

    def upsert_leads(self, leads: list[EnrichedB2BLead]) -> int:
        if not leads:
            return 0
        rows: list[tuple[Any, ...]] = [
            (
                item.domain,
                item.tld,
                item.tranco_rank,
                item.company_number,
                item.legal_name,
                item.legal_form,
                item.federal_state,
                item.city,
                item.postal_code,
                item.ceo_name,
                json.dumps(item.all_ceos, ensure_ascii=False),
                item.email,
                json.dumps(item.all_emails, ensure_ascii=False),
                item.phone,
                item.vat_id,
                item.register_code,
                item.register_court,
                item.primary_cms,
                item.primary_crm,
                item.consent_cmp,
                item.is_ecommerce,
                item.has_meta_pixel,
                item.has_google_ads,
                item.has_gtm,
                item.has_ga4,
                item.has_tiktok_pixel,
                item.has_linkedin_pixel,
                item.has_pinterest_pixel,
                item.has_microsoft_uet,
                json.dumps(item.ad_pixels, ensure_ascii=False),
                json.dumps(item.tech_stack, ensure_ascii=False),
                item.instagram_url,
                item.linkedin_url,
                item.tiktok_url,
                item.facebook_url,
                item.lead_score,
                item.pitch_segment,
                item.pitch_angle,
                item.transport_tier,
                item.pages_crawled,
                item.impressum_url,
                item.site_title,
                item.http_status,
                item.exported_to_crm,
                item.crawled_at,
            )
            for item in leads
        ]
        sql = """
            INSERT INTO b2b_leads (
                domain, tld, tranco_rank, company_number, legal_name, legal_form, federal_state, city,
                postal_code, ceo_name, all_ceos, email, all_emails, phone, vat_id, register_code,
                register_court, primary_cms, primary_crm, consent_cmp, is_ecommerce,
                has_meta_pixel, has_google_ads, has_gtm, has_ga4, has_tiktok_pixel, has_linkedin_pixel,
                has_pinterest_pixel, has_microsoft_uet, ad_pixels, tech_stack,
                instagram_url, linkedin_url, tiktok_url, facebook_url,
                lead_score, pitch_segment, pitch_angle, transport_tier, pages_crawled,
                impressum_url, site_title, http_status, exported_to_crm, crawled_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (domain) DO UPDATE SET
                company_number = EXCLUDED.company_number,
                legal_name = EXCLUDED.legal_name,
                legal_form = EXCLUDED.legal_form,
                federal_state = EXCLUDED.federal_state,
                city = EXCLUDED.city,
                postal_code = EXCLUDED.postal_code,
                ceo_name = EXCLUDED.ceo_name,
                all_ceos = EXCLUDED.all_ceos,
                email = EXCLUDED.email,
                all_emails = EXCLUDED.all_emails,
                phone = EXCLUDED.phone,
                vat_id = EXCLUDED.vat_id,
                register_code = EXCLUDED.register_code,
                register_court = EXCLUDED.register_court,
                primary_cms = EXCLUDED.primary_cms,
                primary_crm = EXCLUDED.primary_crm,
                consent_cmp = EXCLUDED.consent_cmp,
                is_ecommerce = EXCLUDED.is_ecommerce,
                has_meta_pixel = EXCLUDED.has_meta_pixel,
                has_google_ads = EXCLUDED.has_google_ads,
                has_gtm = EXCLUDED.has_gtm,
                has_ga4 = EXCLUDED.has_ga4,
                has_tiktok_pixel = EXCLUDED.has_tiktok_pixel,
                has_linkedin_pixel = EXCLUDED.has_linkedin_pixel,
                has_pinterest_pixel = EXCLUDED.has_pinterest_pixel,
                has_microsoft_uet = EXCLUDED.has_microsoft_uet,
                ad_pixels = EXCLUDED.ad_pixels,
                tech_stack = EXCLUDED.tech_stack,
                instagram_url = EXCLUDED.instagram_url,
                linkedin_url = EXCLUDED.linkedin_url,
                tiktok_url = EXCLUDED.tiktok_url,
                facebook_url = EXCLUDED.facebook_url,
                lead_score = EXCLUDED.lead_score,
                pitch_segment = EXCLUDED.pitch_segment,
                pitch_angle = EXCLUDED.pitch_angle,
                transport_tier = EXCLUDED.transport_tier,
                pages_crawled = EXCLUDED.pages_crawled,
                impressum_url = EXCLUDED.impressum_url,
                site_title = EXCLUDED.site_title,
                http_status = EXCLUDED.http_status,
                crawled_at = EXCLUDED.crawled_at;
        """
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.executemany(sql, rows)
            conn.commit()
        return len(rows)
