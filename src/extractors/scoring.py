"""Deterministic B2B Lead Scoring (0-100), Brand Slug Normalizer, and Agency Ad-Spend Gap Segmentation."""

from __future__ import annotations

import re

from src.models.lead import AdTechProfile, ImpressumContacts, LeadScoreResult

LEGAL_SUFFIX_NOISE_RE = re.compile(
    r"\b(?:gmbh|ug|haftungsbeschraenkt|haftungsbeschränkt|aktiengesellschaft|ag|se|kgaa|kg|ohg|gbr|"
    r"co|ek|e\.k\.|ev|mbh|holding|group|gruppe|deutschland|germany|dach|europe|international|verwaltungs|beteiligungs)\b",
    re.IGNORECASE,
)
UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
GENERIC_EMAIL_PREFIXES = ("info", "kontakt", "contact", "office", "mail", "hello", "hallo", "service", "support")
PRIVACY_EMAIL_PREFIXES = ("datenschutz", "privacy", "dpo", "dsb")
B2B_CORPORATE_FORMS = {"GmbH", "GmbH & Co. KG", "AG", "SE", "KG", "OHG", "UG"}


def normalize_brand_slug(raw_name_or_domain: str) -> str:
    """Normalize a legal company name or domain into an alphanumeric brand slug for entity resolution."""
    val = raw_name_or_domain.strip().lower().translate(UMLAUT_MAP)
    if "." in val and " " not in val:
        # Strip scheme & TLD from domain like "www.thomann.de" -> "thomann"
        val = val.split("://")[-1].split("/")[0]
        if val.startswith("www."):
            val = val[4:]
        val = val.split(".")[0]
    else:
        val = LEGAL_SUFFIX_NOISE_RE.sub(" ", val)
    slug = NON_ALNUM_RE.sub("", val)
    return slug if len(slug) >= 3 else ""


class LeadScorer:
    """Computes deterministic Lead Score (0..100) and agency Ad-Spend Gap segment."""

    @classmethod
    def score(
        cls,
        contacts: ImpressumContacts,
        adtech: AdTechProfile,
        registry_matched: bool = False,
    ) -> LeadScoreResult:
        points = 0

        # 1. Contact & Decision-Maker Completeness (up to 60 pts)
        if contacts.primary_email:
            prefix = contacts.primary_email.split("@")[0].lower()
            if prefix.startswith(PRIVACY_EMAIL_PREFIXES):
                points += 8
            elif prefix.startswith(GENERIC_EMAIL_PREFIXES):
                points += 18
            else:
                points += 25

        if contacts.ceo_names:
            points += 20

        if contacts.primary_phone:
            points += 5

        if contacts.register_id or contacts.vat_id or registry_matched:
            points += 10

        # 2. Tech Stack & Paid Acquisition Signals (up to 25 pts)
        if adtech.is_ecommerce:
            points += 15
        elif adtech.primary_cms:
            points += 8

        has_paid_social = adtech.has_meta_pixel or adtech.has_tiktok_pixel or adtech.has_pinterest_pixel
        has_any_paid_pixel = (
            adtech.has_google_ads
            or has_paid_social
            or adtech.has_linkedin_pixel
            or adtech.has_microsoft_uet
        )
        if has_any_paid_pixel:
            points += 10

        # 3. Determine Commercial Agency Pitch Segment & Gap Bonus (up to 15 pts)
        cms_label = adtech.primary_cms or ("E-Commerce" if adtech.is_ecommerce else "Corporate Site")

        if adtech.has_google_ads and not has_paid_social:
            segment = "PAID_SEARCH_MISSING_SOCIAL"
            angle = (
                f"Runs Google Ads on {cms_label} (proven ad spend), "
                "but missing Meta & TikTok retargeting pixels — high-ROI Paid Social pitch."
            )
            points += 15
        elif has_paid_social and not adtech.has_google_ads:
            segment = "PAID_SOCIAL_MISSING_SEARCH"
            angle = (
                f"Active Paid Social pixels on {cms_label} without Google Ads conversion tag "
                "— high-intent Google Search/Shopping capture pitch."
            )
            points += 15
        elif adtech.is_ecommerce and not adtech.primary_crm:
            segment = "ECOM_NO_RETENTION_CRM"
            angle = (
                f"Active {cms_label} storefront without dedicated retention/email CRM "
                "(Klaviyo / HubSpot / ActiveCampaign) — lifecycle revenue pitch."
            )
            points += 15
        elif adtech.is_ecommerce and not has_any_paid_pixel:
            segment = "ORGANIC_ECOM_NO_PIXELS"
            angle = (
                f"Live {cms_label} store operating purely organically with zero paid ad pixels "
                "— full-funnel performance marketing pitch."
            )
            points += 13
        elif (
            (contacts.legal_form in B2B_CORPORATE_FORMS or registry_matched)
            and (adtech.has_gtm or adtech.has_ga4 or adtech.has_google_ads)
            and not (adtech.has_linkedin_pixel and adtech.primary_crm)
        ):
            segment = "B2B_HIGH_TICKET_GAPS"
            angle = (
                f"Verified DACH {contacts.legal_form or 'B2B'} entity with analytics/search tracking, "
                "missing LinkedIn Insight B2B retargeting or HubSpot CRM automation."
            )
            points += 12
        elif has_any_paid_pixel and adtech.primary_crm:
            segment = "FULL_STACK_MATURE"
            angle = (
                f"Mature multi-channel stack ({cms_label} + {adtech.primary_crm} + paid pixels) "
                "— creative testing & ROAS audit pitch."
            )
            points += 8
        elif contacts.primary_email or contacts.ceo_names:
            segment = "GENERAL_SMB_OUTREACH"
            angle = f"Verified DACH business contact ({cms_label}) with minimal MarTech footprint — digital modernization pitch."
            points += 5
        else:
            segment = "LOW_SIGNAL_UNQUALIFIED"
            angle = "Insufficient contact or MarTech signals on public pages."

        return LeadScoreResult(
            lead_score=min(100, points),
            pitch_segment=segment,
            pitch_angle=angle,
        )
