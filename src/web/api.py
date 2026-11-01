"""FastAPI REST API serving <100ms DuckDB OLAP queries over 1M+ rows, Scrapy worker jobs, and n8n webhooks."""

from __future__ import annotations

import csv
import io
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from config.settings import PROJECT_ROOT, settings
from src.seeders.frontier import get_redis_queue_status, push_frontier_to_redis
from src.storage.duckdb_store import DuckDBStore

STATIC_DIR = Path(__file__).resolve().parent / "static"


class CrawlJobRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=5000)
    domains: str = Field(default="", description="Optional comma-separated domains")
    concurrency: int = Field(default=32, ge=1, le=256)
    force_curl_cffi: bool = False


class MarkExportedRequest(BaseModel):
    domains: list[str] = Field(default_factory=list)


class RedisEnqueueRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=100_000)


class CrawlWorkerManager:
    """Manages isolated Scrapy worker subprocesses so Twisted reactor restarts cleanly across UI runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._logs: deque[str] = deque(maxlen=250)
        self._last_exit_code: int | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            if self._proc is not None and not running:
                self._last_exit_code = self._proc.returncode
            return {
                "running": running,
                "pid": self._proc.pid if running and self._proc else None,
                "last_exit_code": self._last_exit_code,
                "logs": list(self._logs),
            }

    def start_job(self, req: CrawlJobRequest) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise HTTPException(status_code=409, detail="A Scrapy crawl worker is already running.")

            self._logs.clear()
            cmd = [
                sys.executable,
                "-m",
                "src.cli",
                "crawl",
                "--limit",
                str(req.limit),
                "--concurrency",
                str(req.concurrency),
                "--log-level",
                "INFO",
            ]
            if req.domains.strip():
                cmd.extend(["--domains", req.domains.strip()])
            if req.force_curl_cffi:
                cmd.append("--force-curl-cffi")

            self._logs.append(f"$ {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._proc = proc

            def _reader() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    with self._lock:
                        self._logs.append(line.rstrip())
                proc.wait()
                with self._lock:
                    self._last_exit_code = proc.returncode
                    self._logs.append(f"[Worker exited with code {proc.returncode}]")

            threading.Thread(target=_reader, daemon=True).start()
            return {"started": True, "pid": proc.pid, "command": cmd}


def generate_outreach_pitch_draft(lead: dict[str, Any]) -> dict[str, str]:
    """Deterministic German B2B outreach draft generator used by UI preview and n8n fallback."""
    ceo = lead.get("ceo_name") or ""
    salutation = f"Hallo {ceo}," if ceo else f"Hallo Team von {lead.get('legal_name') or lead['domain']},"
    cms = lead.get("primary_cms") or "Ihrem Online-Auftritt"
    seg = lead.get("pitch_segment") or ""

    if seg == "PAID_SEARCH_MISSING_SOCIAL":
        hook = (
            f"mir ist aufgefallen, dass Sie über {lead['domain']} ({cms}) bereits aktiv Google Ads schalten, "
            "aktuell jedoch weder ein Meta Pixel noch ein TikTok Retargeting-Tag eingebunden ist."
        )
        value = "Gerade Besucher aus bezahlter Google-Suche konvertieren im Paid-Social-Retargeting oft mit 3-4x ROAS."
    elif seg == "PAID_SOCIAL_MISSING_SEARCH":
        hook = (
            f"Sie nutzen auf {lead['domain']} ({cms}) bereits aktives Paid-Social-Tracking, "
            "verzichten aber aktuell auf Google Ads Conversion-Tracking für kaufbereite Suchanfragen."
        )
        value = "Damit entgeht Ihnen oft genau der High-Intent-Traffic, den Ihre Social-Kampagnen vorwärmen."
    elif seg == "ECOM_NO_RETENTION_CRM":
        hook = (
            f"Ihr Shop auf {lead['domain']} ({cms}) ist stark aufgestellt, allerdings konnten wir keine "
            "dedizierte E-Mail-/Retention-Automatisierung wie Klaviyo oder HubSpot erkennen."
        )
        value = "Typischerweise lassen sich im DACH E-Commerce 20-30% Zusatzumsatz allein über automatisierte Flows heben."
    else:
        hook = (
            f"bei einer kurzen technischen Analyse von {lead['domain']} ({cms}) haben wir ungenutztes "
            "Performance- & Tracking-Potenzial im DACH-Markt identifiziert."
        )
        value = "Mit sauberem Full-Funnel-Tracking senken unsere B2B- und E-Commerce-Kunden ihre CPA spürbar."

    subject = f"Kurze Frage zu {lead['domain']} / Performance-Setup"
    body = (
        f"{salutation}\n\n"
        f"{hook}\n\n"
        f"{value}\n\n"
        "Hätten Sie nächste Woche 10 Minuten Zeit für einen kurzen technischen Blick auf Ihr Setup?\n\n"
        "Beste Grüße"
    )
    return {"subject": subject, "body_de": body}


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="DACH B2B LeadGen & Ad-Tech Intelligence API",
        version="0.1.0",
        description="1M+ Row Handelsregister & Live Scrapy Ad-Tech Lead Explorer with n8n Agency Automation",
    )
    store = DuckDBStore(db_path=db_path)
    worker_mgr = CrawlWorkerManager()

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html_file = STATIC_DIR / "index.html"
        return HTMLResponse(html_file.read_text(encoding="utf-8"))

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "storage_mode": settings.storage_mode,
            "duckdb_path": str(store.db_path),
            "redis": get_redis_queue_status(),
        }

    @app.get("/api/v1/stats")
    def stats() -> dict[str, Any]:
        data = store.get_dashboard_stats()
        data["redis"] = get_redis_queue_status()
        data["worker"] = worker_mgr.status()
        return data

    @app.get("/api/v1/leads")
    def list_leads(
        search: str = Query(default=""),
        min_score: int = Query(default=0, ge=0, le=100),
        cms: str = Query(default=""),
        pitch_segment: str = Query(default=""),
        require_pixel: str = Query(default=""),
        missing_pixel: str = Query(default=""),
        has_email: bool = Query(default=False),
        has_ceo: bool = Query(default=False),
        federal_state: str = Query(default=""),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return store.query_leads(
            search=search,
            min_score=min_score,
            cms=cms,
            pitch_segment=pitch_segment,
            require_pixel=require_pixel,
            missing_pixel=missing_pixel,
            has_email=has_email,
            has_ceo=has_ceo,
            federal_state=federal_state,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/v1/registry")
    def list_registry(
        search: str = Query(default=""),
        federal_state: str = Query(default=""),
        legal_form: str = Query(default=""),
        has_ceo: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=250),
    ) -> dict[str, Any]:
        return store.query_registry_entities(
            search=search,
            federal_state=federal_state,
            legal_form=legal_form,
            has_ceo=has_ceo,
            limit=limit,
        )

    @app.get("/api/v1/export/csv")
    def export_filtered_csv(
        search: str = Query(default=""),
        min_score: int = Query(default=0, ge=0, le=100),
        cms: str = Query(default=""),
        pitch_segment: str = Query(default=""),
        require_pixel: str = Query(default=""),
        missing_pixel: str = Query(default=""),
        has_email: bool = Query(default=False),
        has_ceo: bool = Query(default=False),
    ) -> StreamingResponse:
        res = store.query_leads(
            search=search,
            min_score=min_score,
            cms=cms,
            pitch_segment=pitch_segment,
            require_pixel=require_pixel,
            missing_pixel=missing_pixel,
            has_email=has_email,
            has_ceo=has_ceo,
            limit=5000,
        )
        buf = io.StringIO()
        fields = [
            "domain",
            "legal_name",
            "legal_form",
            "federal_state",
            "city",
            "ceo_name",
            "email",
            "phone",
            "vat_id",
            "register_code",
            "primary_cms",
            "primary_crm",
            "consent_cmp",
            "is_ecommerce",
            "has_meta_pixel",
            "has_google_ads",
            "has_gtm",
            "has_tiktok_pixel",
            "has_linkedin_pixel",
            "lead_score",
            "pitch_segment",
            "pitch_angle",
            "transport_tier",
            "impressum_url",
        ]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in res["items"]:
            writer.writerow(row)

        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="dach_b2b_leads_filtered.csv"'},
        )

    @app.get("/api/v1/export/parquet")
    def export_parquet() -> FileResponse:
        p_path, _ = store.export_leads_showcase(limit=5000)
        return FileResponse(
            path=p_path,
            media_type="application/octet-stream",
            filename="dach_b2b_leads.parquet",
        )

    @app.post("/api/v1/crawl/start")
    def start_crawl(req: CrawlJobRequest) -> dict[str, Any]:
        return worker_mgr.start_job(req)

    @app.get("/api/v1/crawl/status")
    def crawl_status() -> dict[str, Any]:
        return worker_mgr.status()

    @app.post("/api/v1/redis/enqueue")
    def redis_enqueue(req: RedisEnqueueRequest) -> dict[str, Any]:
        try:
            pushed = push_frontier_to_redis(store=store, limit=req.limit)
            return {"enqueued": pushed, "redis_key": settings.redis_start_urls_key}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Redis connection unavailable: {exc}") from exc

    @app.get("/api/v1/n8n/hot-leads")
    def n8n_hot_leads(
        min_score: int = Query(default=settings.hot_lead_score_threshold, ge=0, le=100),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        leads = store.fetch_unprocessed_hot_leads(min_score=min_score, limit=limit)
        enriched_outreach = []
        for lead in leads:
            draft = generate_outreach_pitch_draft(lead)
            enriched_outreach.append({**lead, "outreach_draft": draft})
        return {"count": len(enriched_outreach), "min_score": min_score, "leads": enriched_outreach}

    @app.post("/api/v1/n8n/mark-exported")
    def n8n_mark_exported(req: MarkExportedRequest) -> dict[str, Any]:
        updated = store.mark_leads_exported(req.domains)
        return {"updated": updated}

    return app


app = create_app()
