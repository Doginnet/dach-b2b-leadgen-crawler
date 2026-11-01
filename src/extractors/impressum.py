"""Deterministic German §5 DDG Impressum & Kontakt extractor built on selectolax."""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from src.models.lead import ImpressumContacts

IMPRESSUM_LINK_RE = re.compile(
    r"\b(impressum|imprint|legal[\-_ ]?notice|rechtliches|anbieterkennzeichnung)\b",
    re.IGNORECASE,
)
CONTACT_LINK_RE = re.compile(
    r"\b(kontakt|contact|ueber[\-_ ]?uns|über[\-_ ]?uns|about[\-_ ]?us)\b",
    re.IGNORECASE,
)
SKIP_EXT_RE = re.compile(r"\.(?:pdf|jpg|jpeg|png|gif|svg|webp|zip|mp4|xml|json)(?:\?|$)", re.IGNORECASE)

# Email extraction + de-obfuscation (e.g. "info [at] firma.de", "kontakt(at)firma.de")
OBFUSCATED_AT_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+|@)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,12})",
    re.IGNORECASE,
)
STRICT_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,12}$")
JUNK_EMAIL_DOMAIN_FRAGMENTS = (
    "sentry.io",
    "wixpress.com",
    "example.com",
    "example.org",
    "example.de",
    "yourdomain",
    "domain.de",
    "mustermann",
    "schema.org",
    "w3.org",
    "cloudflare.com",
)
JUNK_EMAIL_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css", ".woff", ".woff2")
PRIVACY_EMAIL_PREFIXES = ("datenschutz", "privacy", "dpo", "dsb", "abuse", "noreply", "no-reply")

# DACH VAT IDs: Germany (DE + 9 digits), Austria (ATU + 8 digits), Switzerland (CHE-xxx.xxx.xxx)
VAT_ID_RE = re.compile(
    r"\b(DE\s?\d{3}\s?\d{3}\s?\d{3}|ATU\s?\d{8}|CHE[\-\s]?\d{3}\.?\d{3}\.?\d{3})\b",
    re.IGNORECASE,
)

# German Handelsregister: HRB / HRA / GnR / PR / VR + digits
REGISTER_CODE_RE = re.compile(
    r"\b(HRB|HRA|GnR|PR|VR)\s*[\-.:#Nr]*\s*(\d{2,7})\b",
    re.IGNORECASE,
)
REGISTER_COURT_RE = re.compile(
    r"\b(Amtsgericht[ \t]+[A-ZÄÖÜ][a-zäöüß\-]+"
    r"(?:[ \t]+(?:am|an[ \t]+der|i\.[ \t]*Br\.|(?!Registernummer|Handelsregister|HRB|HRA|Umsatzsteuer|USt|Steuernummer|Telefon)[A-ZÄÖÜ][a-zäöüß\-]+))?)",
)

# German / DACH legal entity forms
LEGAL_ENTITY_RE = re.compile(
    r"(?:^|\n)\s*([A-ZÄÖÜ0-9][A-Za-zÄÖÜäöüß0-9&.,\-/'() ]{1,75}?\s+"
    r"(?:GmbH\s*&\s*Co\.\s*KG|GmbH\s*&\s*Co\.\s*OHG|UG\s*\(haftungsbeschränkt\)\s*&\s*Co\.\s*KG|"
    r"UG\s*\(haftungsbeschränkt\)|GmbH|Aktiengesellschaft|AG|SE\s*&\s*Co\.\s*KGaA|SE|KGaA|OHG|KG|GbR|e\.K\.|e\.Kfm\.|e\.V\.))(?=\s*(?:$|\n|,|\|))",
    re.MULTILINE,
)

# Decision makers (Geschäftsführer, Vorstand, Inhaber, Vertreten durch)
CEO_BLOCK_RE = re.compile(
    r"(?:Geschäftsführer(?:in|innen)?|Geschäftsführung|Vertretungsberechtigte[r]?\s+Geschäftsführer(?:in)?|"
    r"Vertreten\s+durch(?:\s+die\s+Geschäftsführer(?:in|innen)?)?|Vorstand(?:svorsitzende[r]?)?|"
    r"Inhaber(?:in)?|Managing\s+Director[s]?|CEO)"
    r"\s*(?:[:\-–]\s*|\n\s*)([^\n]{4,140}(?:\n\s*(?:Dr\.|Prof\.|[A-ZÄÖÜ][a-zäöüß]+)\s+[A-ZÄÖÜ][a-zäöüß\-]+){0,3})",
    re.IGNORECASE,
)
CEO_STOPWORDS = {
    "registergericht",
    "amtsgericht",
    "handelsregister",
    "umsatzsteuer",
    "ust",
    "telefon",
    "telefax",
    "kontakt",
    "mail",
    "inhaltlich",
    "verantwortlich",
    "gemäß",
    "gemaess",
    "steuernummer",
    "aufsichtsbehörde",
    "kammer",
    "impressum",
    "datenschutz",
    "adresse",
    "anschrift",
    "sitz",
    "gesellschaft",
    "vorstand",
    "geschäftsführer",
}
PERSON_NAME_RE = re.compile(
    r"^(?:(?:Dr\.|Prof\.|Dipl\.-[A-Za-z]+|Mag\.|MBA)\s+)*"
    r"[A-ZÄÖÜ][a-zäöüß\-]{1,25}(?:\s+[A-ZÄÖÜ]\.?)?(?:\s+(?:von|van|de|zu|der))?\s+"
    r"[A-ZÄÖÜ][a-zäöüß\-]{1,30}(?:\s+[A-ZÄÖÜ][a-zäöüß\-]{1,25})?$"
)

PHONE_LABELED_RE = re.compile(
    r"(?:Tel(?:efon)?\.?|Phone|Fon|Zentrale)\s*[:\-–]?\s*(\+?(?:49|43|41|0)\s*[\d\s()/\-–]{6,22}\d)",
    re.IGNORECASE,
)
POSTAL_CITY_RE = re.compile(
    r"\b(?:D-|DE-|AT-|CH-)?(\d{4,5})[ \t]+([A-ZÄÖÜ][a-zäöüß\-]+"
    r"(?:[ \t]+(?:am|an[ \t]+der|im|bei)[ \t]+[A-ZÄÖÜ][a-zäöüß\-]+|[ \t]+(?!Vertreten|Geschäftsführer|Telefon|Register|Umsatzsteuer|E-Mail)[A-ZÄÖÜ][a-zäöüß\-]+)?)\b"
)

SOCIAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "instagram": re.compile(r"^https?://(?:www\.)?instagram\.com/(?!p/|reel/|explore/)([A-Za-z0-9._]{2,40})/?", re.I),
    "linkedin": re.compile(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in)/([A-Za-z0-9\-_%]{2,80})/?", re.I),
    "tiktok": re.compile(r"^https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._]{2,40})/?", re.I),
    "facebook": re.compile(
        r"^https?://(?:www\.|de-de\.)?facebook\.com/(?!sharer|share\.php|dialog|tr\?)([A-Za-z0-9.\-]{2,60})/?",
        re.I,
    ),
}


def classify_legal_form(legal_name: str) -> str:
    """Classify DACH corporate legal form from company name."""
    upper = legal_name.upper()
    if "GMBH & CO. KG" in upper or "GMBH & CO KG" in upper:
        return "GmbH & Co. KG"
    if "UG (HAFTUNGSBESCHR" in upper or re.search(r"\bUG\b", upper):
        return "UG"
    if "GMBH" in upper:
        return "GmbH"
    if "AKTIENGESELLSCHAFT" in upper or re.search(r"\bAG\b", upper):
        return "AG"
    if re.search(r"\bSE\b", upper):
        return "SE"
    if re.search(r"\bOHG\b", upper):
        return "OHG"
    if re.search(r"\bKG\b", upper):
        return "KG"
    if "E.K" in upper or "E. K" in upper:
        return "e.K."
    if "GBR" in upper:
        return "GbR"
    return "Other"


def _registrable_host(netloc: str) -> str:
    host = netloc.split(":")[0].lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class ImpressumExtractor:
    """Zero-selector §5 DDG German Impressum & Contact Intelligence parser."""

    @staticmethod
    def extract_title(html: str) -> str:
        tree = HTMLParser(html)
        node = tree.css_first("title")
        if not node:
            return ""
        return re.sub(r"\s+", " ", node.text(strip=True))[:160]

    @classmethod
    def discover_target_links(cls, html: str, base_url: str, max_links: int = 2) -> list[str]:
        """Discover same-domain /impressum and /kontakt URLs from homepage DOM."""
        tree = HTMLParser(html)
        base_reg = _registrable_host(urlparse(base_url).netloc)

        impressum_candidates: list[str] = []
        contact_candidates: list[str] = []
        seen: set[str] = set()

        for node in tree.css("a[href]"):
            raw_href = (node.attributes.get("href") or "").strip()
            if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            full_url = urljoin(base_url, raw_href).split("#")[0].rstrip("/")
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue
            if _registrable_host(parsed.netloc) != base_reg:
                continue
            if SKIP_EXT_RE.search(parsed.path):
                continue
            if full_url == base_url.rstrip("/") or full_url in seen:
                continue

            anchor_text = node.text(strip=True)[:80]
            probe_str = f"{parsed.path} {anchor_text}"

            if IMPRESSUM_LINK_RE.search(probe_str):
                seen.add(full_url)
                impressum_candidates.append(full_url)
            elif CONTACT_LINK_RE.search(probe_str):
                seen.add(full_url)
                contact_candidates.append(full_url)

        # Prioritize shortest clean path (e.g. /impressum ahead of /de/blog/impressum-infos)
        impressum_candidates.sort(key=len)
        contact_candidates.sort(key=len)
        ordered = [*impressum_candidates[:1], *contact_candidates[:1], *impressum_candidates[1:], *contact_candidates[1:]]
        return ordered[:max_links]

    @classmethod
    def extract(cls, html: str) -> ImpressumContacts:
        tree = HTMLParser(html)

        mailto_emails: list[str] = []
        tel_phones: list[str] = []
        socials: dict[str, str] = {}

        for a_node in tree.css("a[href]"):
            href = (a_node.attributes.get("href") or "").strip()
            if not href:
                continue
            lower_href = href.lower()
            if lower_href.startswith("mailto:"):
                raw_mail = unquote(href[7:].split("?")[0]).strip()
                mailto_emails.append(raw_mail)
            elif lower_href.startswith("tel:"):
                raw_tel = unquote(href[4:].split("?")[0]).strip()
                if sum(ch.isdigit() for ch in raw_tel) >= 7:
                    tel_phones.append(raw_tel)
            elif lower_href.startswith(("http://", "https://")):
                for platform, pattern in SOCIAL_PATTERNS.items():
                    if platform not in socials and pattern.search(href):
                        socials[platform] = href.split("?")[0].rstrip("/")

        # Strip non-visible tags before extracting structured newline text
        for tag in tree.css("script, style, noscript, svg, template"):
            tag.decompose()

        clean_text = tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")
        clean_text = re.sub(r"[ \t\r\f\v]+", " ", clean_text)
        clean_text = re.sub(r"\n(?:\s*\n)+", "\n", clean_text)

        emails = cls._extract_emails(clean_text, mailto_emails)
        primary_email = cls._pick_primary_email(emails)

        phones = cls._extract_phones(clean_text, tel_phones)
        vat_id = cls._extract_vat_id(clean_text)
        reg_type, reg_id, reg_court = cls._extract_register_info(clean_text)
        legal_name = cls._extract_legal_name(clean_text)
        ceo_names = cls._extract_ceos(clean_text)
        postal_code, city = cls._extract_postal_city(clean_text)

        return ImpressumContacts(
            legal_name=legal_name,
            legal_form=classify_legal_form(legal_name) if legal_name else "",
            ceo_names=ceo_names,
            emails=emails,
            primary_email=primary_email,
            phones=phones,
            primary_phone=phones[0] if phones else "",
            vat_id=vat_id,
            register_type=reg_type,
            register_id=reg_id,
            register_court=reg_court,
            postal_code=postal_code,
            city=city,
            social_links=socials,
        )

    @classmethod
    def merge(cls, primary: ImpressumContacts, secondary: ImpressumContacts) -> ImpressumContacts:
        """Merge Impressum page contacts (priority) with Homepage / Kontakt page contacts."""
        emails = list(dict.fromkeys([*primary.emails, *secondary.emails]))
        phones = list(dict.fromkeys([*primary.phones, *secondary.phones]))
        ceos = list(dict.fromkeys([*primary.ceo_names, *secondary.ceo_names]))
        socials = {**secondary.social_links, **primary.social_links}
        legal_name = primary.legal_name or secondary.legal_name
        return ImpressumContacts(
            legal_name=legal_name,
            legal_form=classify_legal_form(legal_name) if legal_name else (primary.legal_form or secondary.legal_form),
            ceo_names=ceos[:5],
            emails=emails[:8],
            primary_email=cls._pick_primary_email(emails),
            phones=phones[:5],
            primary_phone=phones[0] if phones else "",
            vat_id=primary.vat_id or secondary.vat_id,
            register_type=primary.register_type or secondary.register_type,
            register_id=primary.register_id or secondary.register_id,
            register_court=primary.register_court or secondary.register_court,
            postal_code=primary.postal_code or secondary.postal_code,
            city=primary.city or secondary.city,
            social_links=socials,
        )

    @staticmethod
    def _extract_emails(text: str, mailto_candidates: list[str]) -> list[str]:
        candidates = list(mailto_candidates)
        for local_part, domain_part in OBFUSCATED_AT_RE.findall(text):
            candidates.append(f"{local_part}@{domain_part}")

        valid: list[str] = []
        seen: set[str] = set()
        for raw in candidates:
            email = raw.strip().strip(".,;:()[]<>\"'").lower()
            if not STRICT_EMAIL_RE.match(email):
                continue
            if email.endswith(JUNK_EMAIL_EXT):
                continue
            if any(bad in email for bad in JUNK_EMAIL_DOMAIN_FRAGMENTS):
                continue
            if email not in seen:
                seen.add(email)
                valid.append(email)
        return valid

    @staticmethod
    def _pick_primary_email(emails: list[str]) -> str:
        if not emails:
            return ""
        non_privacy = [
            e for e in emails if not e.split("@")[0].startswith(PRIVACY_EMAIL_PREFIXES)
        ]
        if not non_privacy:
            return emails[0]
        # Prefer direct personal / leadership / sales email over generic info@ if available
        generic_prefixes = ("info", "kontakt", "contact", "office", "mail", "hello", "hallo", "service", "support")
        direct = [e for e in non_privacy if not e.split("@")[0].startswith(generic_prefixes)]
        return direct[0] if direct else non_privacy[0]

    @staticmethod
    def _extract_phones(text: str, tel_candidates: list[str]) -> list[str]:
        raw_list = [*tel_candidates, *(m.group(1) for m in PHONE_LABELED_RE.finditer(text))]
        cleaned: list[str] = []
        seen_digits: set[str] = set()
        for raw in raw_list:
            norm = re.sub(r"\s+", " ", raw).strip(" .,-–/")
            digits = "".join(ch for ch in norm if ch.isdigit())
            if 7 <= len(digits) <= 16 and digits not in seen_digits:
                seen_digits.add(digits)
                cleaned.append(norm)
        return cleaned

    @staticmethod
    def _extract_vat_id(text: str) -> str:
        match = VAT_ID_RE.search(text)
        if not match:
            return ""
        raw = re.sub(r"\s+", "", match.group(1)).upper()
        return raw

    @staticmethod
    def _extract_register_info(text: str) -> tuple[str, str, str]:
        reg_type = ""
        reg_id = ""
        reg_court = ""
        code_match = REGISTER_CODE_RE.search(text)
        if code_match:
            reg_type = code_match.group(1).upper()
            if reg_type == "GNR":
                reg_type = "GnR"
            reg_id = code_match.group(2)
        court_match = REGISTER_COURT_RE.search(text)
        if court_match:
            reg_court = re.sub(r"\s+", " ", court_match.group(1)).strip()
        return reg_type, reg_id, reg_court

    @staticmethod
    def _extract_legal_name(text: str) -> str:
        for match in LEGAL_ENTITY_RE.finditer(text):
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,|-:")
            if 4 <= len(candidate) <= 95 and not candidate.lower().startswith(("registergericht", "amtsgericht")):
                return candidate
        return ""

    @staticmethod
    def _extract_ceos(text: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for match in CEO_BLOCK_RE.finditer(text):
            block = match.group(1)
            # Split by comma, semicolon, slash, "und", "&", or newline
            parts = re.split(r"[,;/|\n]|\s+und\s+|\s+&\s+", block)
            for part in parts:
                cleaned = re.sub(r"\([^)]*\)", "", part)
                cleaned = re.sub(r"\b(?:Vorsitzende[r]?|CEO|CFO|COO|CTO|geschäftsführende[r]?)\b", "", cleaned, flags=re.I)
                cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-–")
                if not cleaned or len(cleaned) < 5 or len(cleaned) > 55:
                    continue
                lower_tokens = set(re.findall(r"[a-zäöüß]+", cleaned.lower()))
                if lower_tokens & CEO_STOPWORDS:
                    continue
                if PERSON_NAME_RE.match(cleaned) and cleaned.lower() not in seen:
                    seen.add(cleaned.lower())
                    found.append(cleaned)
        return found[:5]

    @staticmethod
    def _extract_postal_city(text: str) -> tuple[str, str]:
        for match in POSTAL_CITY_RE.finditer(text):
            plz, city = match.group(1), match.group(2).strip()
            if city.lower() not in {"uhr", "euro", "eur", "abs", "nr", "tel", "hrb", "hra"}:
                return plz, city
        return "", ""
