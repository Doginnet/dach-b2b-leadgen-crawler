"""Live integration test verifying curl_cffi TLS transport & German §5 DDG Impressum extraction on .de targets."""

from __future__ import annotations

import pytest
from curl_cffi import requests as curl_requests

from src.extractors.adtech import AdTechFingerprinter
from src.extractors.impressum import ImpressumExtractor


@pytest.mark.live
def test_live_german_commercial_domain_extraction() -> None:
    session = curl_requests.Session(impersonate="chrome124")
    resp = session.get("https://www.hetzner.com/de/", timeout=15)
    assert resp.status_code == 200
    html = resp.text

    adtech = AdTechFingerprinter.analyze(html)
    links = ImpressumExtractor.discover_target_links(html, "https://www.hetzner.com/de/", max_links=2)
    assert isinstance(adtech.ad_pixels, list)
    assert len(links) >= 1
