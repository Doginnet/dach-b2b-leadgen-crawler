"""Deterministic Ad-Tech pixel, CMS/E-Commerce, CRM, and GDPR CMP fingerprinter (27 signatures)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.models.lead import AdTechProfile


@dataclass(frozen=True, slots=True)
class TechSignature:
    name: str
    category: str  # "pixel" | "cms" | "crm" | "cmp"
    pattern: re.Pattern[str]
    is_ecommerce: bool = False


COMPILED_SIGNATURES: tuple[TechSignature, ...] = (
    # --- 1. Ad Pixels & Conversion Analytics (8) ---
    TechSignature(
        name="Meta Pixel",
        category="pixel",
        pattern=re.compile(
            r"connect\.facebook\.net/[^\"'\s>]*/fbevents\.js|\bfbq\s*\(\s*['\"]init['\"]|facebook\.com/tr\?id=\d+",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Google Ads",
        category="pixel",
        pattern=re.compile(
            r"googleadservices\.com/pagead/conversion|\bAW-\d{6,12}\b|googlesyndication\.com/pagead",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Google Tag Manager",
        category="pixel",
        pattern=re.compile(
            r"googletagmanager\.com/(?:gtm\.js|ns\.html)\?id=GTM-|\bGTM-[A-Z0-9]{5,10}\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Google Analytics 4",
        category="pixel",
        pattern=re.compile(
            r"googletagmanager\.com/gtag/js\?id=G-[A-Z0-9]+|['\"]G-[A-Z0-9]{7,12}['\"]",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="TikTok Pixel",
        category="pixel",
        pattern=re.compile(
            r"analytics\.tiktok\.com/i18n/pixel|\bttq\.load\s*\(\s*['\"][A-Z0-9]+['\"]",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="LinkedIn Insight Tag",
        category="pixel",
        pattern=re.compile(
            r"snap\.licdn\.com/li\.lms-analytics/insight\.min\.js|\b_linkedin_partner_id\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Pinterest Tag",
        category="pixel",
        pattern=re.compile(
            r"s\.pinimg\.com/ct/core\.js|\bpintrk\s*\(\s*['\"]load['\"]",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Microsoft Clarity / UET",
        category="pixel",
        pattern=re.compile(
            r"bat\.bing\.com/bat\.js|clarity\.ms/tag/[a-z0-9]+",
            re.IGNORECASE,
        ),
    ),
    # --- 2. E-Commerce & Corporate CMS Platforms (9) ---
    TechSignature(
        name="Shopware",
        category="cms",
        is_ecommerce=True,
        pattern=re.compile(
            r"/bundles/storefront/|shopware-storefront|sw-csrf-|/theme/[0-9a-f]{32}/js/all\.js|\bshopware\b[^>]{0,40}storefront",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Shopify",
        category="cms",
        is_ecommerce=True,
        pattern=re.compile(
            r"cdn\.shopify\.com/|Shopify\.shop\s*=|shopify-digital-wallet",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="WooCommerce",
        category="cms",
        is_ecommerce=True,
        pattern=re.compile(
            r"plugins/woocommerce/|wc-cart-fragments|woocommerce-layout|class=[\"'][^\"']*\bwoocommerce\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Magento",
        category="cms",
        is_ecommerce=True,
        pattern=re.compile(
            r"Mage\.Cookies|static/version\d+/frontend/|text/x-magento-init",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="PrestaShop",
        category="cms",
        is_ecommerce=True,
        pattern=re.compile(
            r"\bvar\s+prestashop\s*=|content=[\"']PrestaShop[\"']",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="OXID eShop",
        category="cms",
        is_ecommerce=True,
        pattern=re.compile(
            r"oxid-esales|content=[\"']OXID\s+eShop|\boxscript\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="WordPress",
        category="cms",
        is_ecommerce=False,
        pattern=re.compile(
            r"/wp-content/(?:themes|plugins|uploads)/|/wp-includes/js/|content=[\"']WordPress",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="TYPO3",
        category="cms",
        is_ecommerce=False,
        pattern=re.compile(
            r"typo3conf/ext/|typo3temp/|This website is powered by TYPO3|content=[\"']TYPO3",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Webflow",
        category="cms",
        is_ecommerce=False,
        pattern=re.compile(
            r"data-wf-site=|assets\.website-files\.com|cdn\.prod\.website-files\.com",
            re.IGNORECASE,
        ),
    ),
    # --- 3. CRM, Email & Retention Automation (6) ---
    TechSignature(
        name="Klaviyo",
        category="crm",
        pattern=re.compile(
            r"static\.klaviyo\.com/onsite/js/klaviyo\.js|\b_learnq\.push\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="HubSpot",
        category="crm",
        pattern=re.compile(
            r"js(?:-[a-z0-9]+)?\.hs-scripts\.com/\d+\.js|js(?:-[a-z0-9]+)?\.hsforms\.net/|track\.hubspot\.com",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Mailchimp",
        category="crm",
        pattern=re.compile(
            r"chimpstatic\.com/mcjs-connected|list-manage\.com/subscribe/post",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="ActiveCampaign",
        category="crm",
        pattern=re.compile(
            r"trackcmp\.net/visit|diffuser-cdn\.app-us1\.com",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Intercom",
        category="crm",
        pattern=re.compile(
            r"widget\.intercom\.io/widget/|window\.intercomSettings",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Zendesk",
        category="crm",
        pattern=re.compile(
            r"static\.zdassets\.com/ekr/snippet\.js",
            re.IGNORECASE,
        ),
    ),
    # --- 4. GDPR Consent Management Platforms / CMPs (4) ---
    TechSignature(
        name="Usercentrics",
        category="cmp",
        pattern=re.compile(
            r"app\.usercentrics\.eu/|web\.cmp\.usercentrics\.eu/|usercentrics-cmp",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Cookiebot",
        category="cmp",
        pattern=re.compile(
            r"consent\.cookiebot\.com/uc\.js|\bCookiebot\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="OneTrust",
        category="cmp",
        pattern=re.compile(
            r"cdn\.cookielaw\.org/scripttemplates/otSDKStub\.js|\bOptanonWrapper\b",
            re.IGNORECASE,
        ),
    ),
    TechSignature(
        name="Borlabs Cookie",
        category="cmp",
        pattern=re.compile(
            r"borlabs-cookie|\bBorlabsCookie\b",
            re.IGNORECASE,
        ),
    ),
)

ECOM_CMS_PRIORITY = ("Shopware", "Shopify", "Magento", "OXID eShop", "PrestaShop", "WooCommerce")


class AdTechFingerprinter:
    """Zero-browser HTML & header signature scanner detecting 27 Ad-Tech, CMS, CRM, and CMP tools."""

    @classmethod
    def analyze(cls, html: str, headers_blob: str = "") -> AdTechProfile:
        corpus = f"{headers_blob}\n{html}" if headers_blob else html
        pixels: list[str] = []
        cms_list: list[str] = []
        crm_list: list[str] = []
        cmp_list: list[str] = []
        is_ecom = False

        for sig in COMPILED_SIGNATURES:
            if sig.pattern.search(corpus):
                if sig.category == "pixel":
                    pixels.append(sig.name)
                elif sig.category == "cms":
                    cms_list.append(sig.name)
                    if sig.is_ecommerce:
                        is_ecom = True
                elif sig.category == "crm":
                    crm_list.append(sig.name)
                elif sig.category == "cmp":
                    cmp_list.append(sig.name)

        # Prefer specific e-commerce engine over underlying WordPress when WooCommerce is active
        primary_cms = ""
        for ecom_name in ECOM_CMS_PRIORITY:
            if ecom_name in cms_list:
                primary_cms = ecom_name
                break
        if not primary_cms and cms_list:
            primary_cms = cms_list[0]

        pixel_set = set(pixels)
        return AdTechProfile(
            ad_pixels=pixels,
            cms_ecommerce=cms_list,
            crm_marketing=crm_list,
            consent_cmp=cmp_list,
            has_meta_pixel="Meta Pixel" in pixel_set,
            has_google_ads="Google Ads" in pixel_set,
            has_gtm="Google Tag Manager" in pixel_set,
            has_ga4="Google Analytics 4" in pixel_set,
            has_tiktok_pixel="TikTok Pixel" in pixel_set,
            has_linkedin_pixel="LinkedIn Insight Tag" in pixel_set,
            has_pinterest_pixel="Pinterest Tag" in pixel_set,
            has_microsoft_uet="Microsoft Clarity / UET" in pixel_set,
            is_ecommerce=is_ecom,
            primary_cms=primary_cms,
            primary_crm=crm_list[0] if crm_list else "",
            primary_cmp=cmp_list[0] if cmp_list else "",
        )

    @staticmethod
    def merge(primary: AdTechProfile, secondary: AdTechProfile) -> AdTechProfile:
        """Merge homepage and subpage (e.g. /impressum) Ad-Tech detections."""
        pixels = list(dict.fromkeys([*primary.ad_pixels, *secondary.ad_pixels]))
        cms_list = list(dict.fromkeys([*primary.cms_ecommerce, *secondary.cms_ecommerce]))
        crm_list = list(dict.fromkeys([*primary.crm_marketing, *secondary.crm_marketing]))
        cmp_list = list(dict.fromkeys([*primary.consent_cmp, *secondary.consent_cmp]))

        primary_cms = ""
        for ecom_name in ECOM_CMS_PRIORITY:
            if ecom_name in cms_list:
                primary_cms = ecom_name
                break
        if not primary_cms and cms_list:
            primary_cms = cms_list[0]

        pixel_set = set(pixels)
        return AdTechProfile(
            ad_pixels=pixels,
            cms_ecommerce=cms_list,
            crm_marketing=crm_list,
            consent_cmp=cmp_list,
            has_meta_pixel="Meta Pixel" in pixel_set,
            has_google_ads="Google Ads" in pixel_set,
            has_gtm="Google Tag Manager" in pixel_set,
            has_ga4="Google Analytics 4" in pixel_set,
            has_tiktok_pixel="TikTok Pixel" in pixel_set,
            has_linkedin_pixel="LinkedIn Insight Tag" in pixel_set,
            has_pinterest_pixel="Pinterest Tag" in pixel_set,
            has_microsoft_uet="Microsoft Clarity / UET" in pixel_set,
            is_ecommerce=primary.is_ecommerce or secondary.is_ecommerce,
            primary_cms=primary_cms,
            primary_crm=crm_list[0] if crm_list else "",
            primary_cmp=cmp_list[0] if cmp_list else "",
        )
