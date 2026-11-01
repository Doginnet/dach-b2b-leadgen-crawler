"""Pydantic v2 data contracts for registry entities, Ad-Tech profiles, and enriched B2B leads."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RegistryCompany(BaseModel):
    """Normalized German Handelsregister legal entity streamed from OffeneRegister."""

    company_number: str
    register_type: str = ""
    register_id: str = ""
    native_company_number: str = ""
    legal_name: str
    brand_slug: str = ""
    legal_form: str = "Other"
    current_status: str = "currently registered"
    federal_state: str = ""
    city: str = ""
    postal_code: str = ""
    registered_address: str = ""
    ceo_names: list[str] = Field(default_factory=list)
    matched_domain: str = ""


class AdTechProfile(BaseModel):
    """Detected Ad-Tech tracking pixels, e-commerce/CMS platform, CRM, and GDPR CMP."""

    ad_pixels: list[str] = Field(default_factory=list)
    cms_ecommerce: list[str] = Field(default_factory=list)
    crm_marketing: list[str] = Field(default_factory=list)
    consent_cmp: list[str] = Field(default_factory=list)

    has_meta_pixel: bool = False
    has_google_ads: bool = False
    has_gtm: bool = False
    has_ga4: bool = False
    has_tiktok_pixel: bool = False
    has_linkedin_pixel: bool = False
    has_pinterest_pixel: bool = False
    has_microsoft_uet: bool = False

    is_ecommerce: bool = False
    primary_cms: str = ""
    primary_crm: str = ""
    primary_cmp: str = ""


class ImpressumContacts(BaseModel):
    """Structured legal & decision-maker fields parsed from German §5 DDG Impressum / Kontakt pages."""

    legal_name: str = ""
    legal_form: str = ""
    ceo_names: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    primary_email: str = ""
    phones: list[str] = Field(default_factory=list)
    primary_phone: str = ""
    vat_id: str = ""
    register_type: str = ""
    register_id: str = ""
    register_court: str = ""
    postal_code: str = ""
    city: str = ""
    social_links: dict[str, str] = Field(default_factory=dict)


class LeadScoreResult(BaseModel):
    """Commercial B2B lead score and agency sales angle."""

    lead_score: int = Field(default=0, ge=0, le=100)
    pitch_segment: str = "LOW_SIGNAL_UNQUALIFIED"
    pitch_angle: str = ""


class EnrichedB2BLead(BaseModel):
    """Unified B2B & Ad-Tech Intelligence record persisted to PostgreSQL and DuckDB/Parquet."""

    domain: str
    tld: str = "de"
    tranco_rank: int | None = None
    company_number: str = ""

    legal_name: str = ""
    legal_form: str = ""
    federal_state: str = ""
    city: str = ""
    postal_code: str = ""

    ceo_name: str = ""
    all_ceos: list[str] = Field(default_factory=list)
    email: str = ""
    all_emails: list[str] = Field(default_factory=list)
    phone: str = ""
    vat_id: str = ""
    register_code: str = ""
    register_court: str = ""

    primary_cms: str = ""
    primary_crm: str = ""
    consent_cmp: str = ""
    is_ecommerce: bool = False

    has_meta_pixel: bool = False
    has_google_ads: bool = False
    has_gtm: bool = False
    has_ga4: bool = False
    has_tiktok_pixel: bool = False
    has_linkedin_pixel: bool = False
    has_pinterest_pixel: bool = False
    has_microsoft_uet: bool = False

    ad_pixels: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)

    instagram_url: str = ""
    linkedin_url: str = ""
    tiktok_url: str = ""
    facebook_url: str = ""

    lead_score: int = Field(default=0, ge=0, le=100)
    pitch_segment: str = "LOW_SIGNAL_UNQUALIFIED"
    pitch_angle: str = ""

    transport_tier: str = "twisted"
    pages_crawled: int = 1
    impressum_url: str = ""
    site_title: str = ""
    http_status: int = 200
    exported_to_crm: bool = False
    crawled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
