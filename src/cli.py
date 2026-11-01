"""Unified Rich CLI for 1M-Row Seeding, Distributed Scrapy Crawling, OLAP Stats, Export, and Web UI."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.crawler.runner import run_crawl_process
from src.seeders.domains import seed_domains_to_duckdb
from src.seeders.frontier import push_frontier_to_redis
from src.seeders.offeneregister import seed_handelsregister_to_duckdb
from src.storage.duckdb_store import DuckDBStore

console = Console()


def cmd_seed(args: argparse.Namespace) -> None:
    store = DuckDBStore()
    if not args.domains_only:
        local_bz2 = Path(args.local_bz2) if args.local_bz2 else None
        console.print(f"[bold cyan]Seeding {args.rows:,} German Handelsregister companies into DuckDB...[/]")
        reg_stats = seed_handelsregister_to_duckdb(
            store=store,
            target_rows=args.rows,
            export_parquet=not args.no_parquet,
            local_bz2_path=local_bz2,
        )
        console.print(
            f"[bold green]Handelsregister Seed Complete:[/] {reg_stats['inserted_rows']:,} rows "
            f"in {reg_stats['elapsed_seconds']}s ({reg_stats['rows_per_second']:,} rows/s) | "
            f"Parquet: {reg_stats['parquet_size_mb']} MB"
        )

    if not args.registry_only:
        console.print(f"[bold cyan]Loading up to {args.max_domains:,} DACH (.de/.at/.ch) commercial domains...[/]")
        dom_stats = seed_domains_to_duckdb(store=store, max_domains=args.max_domains)
        console.print(
            f"[bold green]Domain Frontier Ready:[/] {dom_stats['domains_loaded']:,} domains "
            f"({dom_stats['prelinked_to_registry']:,} pre-linked to Handelsregister entities)"
        )


def cmd_crawl(args: argparse.Namespace) -> None:
    explicit = [d.strip() for d in args.domains.split(",") if d.strip()] if args.domains else None
    console.print(
        f"[bold cyan]Launching Scrapy Engine[/] (limit={args.limit}, concurrency={args.concurrency}, "
        f"redis={args.redis}, force_curl_cffi={args.force_curl_cffi})"
    )
    stats = run_crawl_process(
        limit=args.limit,
        domains=explicit,
        concurrent_requests=args.concurrency,
        use_redis=args.redis,
        force_curl_cffi=args.force_curl_cffi,
        log_level=args.log_level,
    )

    table = Table(title="Scrapy Crawl Telemetry")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    keys_of_interest = [
        "downloader/request_count",
        "downloader/response_count",
        "transport/twisted_requests",
        "transport/curl_cffi_requests",
        "antibot/escalated_to_curl_cffi",
        "antibot/exception_escalated_to_curl_cffi",
        "item_scraped_count",
        "storage/duckdb_upserted",
        "storage/postgres_upserted",
        "elapsed_time_seconds",
    ]
    for k in keys_of_interest:
        if k in stats:
            val = stats[k]
            formatted = f"{val:.2f}" if isinstance(val, float) else f"{val}"
            table.add_row(k, formatted)
    console.print(table)

    if args.export_showcase:
        store = DuckDBStore()
        p_path, c_path = store.export_leads_showcase()
        console.print(f"[bold green]Showcase exported:[/] {p_path} & {c_path}")


def cmd_stats(_: argparse.Namespace) -> None:
    store = DuckDBStore()
    data = store.get_dashboard_stats()
    reg = data["registry"]
    fr = data["frontier"]
    ld = data["leads"]

    summary = Table(title=f"Lakehouse & LeadGen OLAP Summary (computed in {data['olap_query_ms']} ms)")
    summary.add_column("Layer", style="cyan")
    summary.add_column("Metric", style="white")
    summary.add_column("Count", style="bold green", justify="right")

    summary.add_row("1M Registry (OffeneRegister)", "Total Legal Entities", f"{reg['total_rows']:,}")
    summary.add_row("1M Registry (OffeneRegister)", "Entities with Verified CEO", f"{reg['with_ceo']:,}")
    summary.add_row("DACH Domain Frontier", "Commercial Domains (.de/.at/.ch)", f"{fr['total_domains']:,}")
    summary.add_row("DACH Domain Frontier", "Pre-Linked via Brand Slug", f"{fr['prelinked_domains']:,}")
    summary.add_row("DACH Domain Frontier", "Live Crawled Domains", f"{fr['crawled_domains']:,}")
    summary.add_row("Enriched B2B Leads", "Total Enriched Leads", f"{ld['total_leads']:,}")
    summary.add_row("Enriched B2B Leads", f"Hot Leads (Score >= {settings.hot_lead_score_threshold})", f"{ld['hot_leads']:,}")
    summary.add_row("Enriched B2B Leads", "Leads with Direct/Corporate Email", f"{ld['with_email']:,}")
    summary.add_row("Enriched B2B Leads", "Leads with Verified CEO/Geschäftsführer", f"{ld['with_ceo']:,}")
    summary.add_row("Enriched B2B Leads", "E-Commerce Storefronts", f"{ld['ecommerce_leads']:,}")
    summary.add_row("Enriched B2B Leads", "Escalated via curl_cffi Chrome124", f"{ld['escalated_curl_cffi']:,}")
    console.print(summary)


def cmd_export(args: argparse.Namespace) -> None:
    store = DuckDBStore()
    p_path, c_path = store.export_leads_showcase(limit=args.limit)
    console.print(f"[bold green]Exported up to {args.limit:,} leads:[/]\n  Parquet: {p_path}\n  CSV:     {c_path}")


def cmd_enqueue_redis(args: argparse.Namespace) -> None:
    store = DuckDBStore()
    pushed = push_frontier_to_redis(store=store, limit=args.limit)
    console.print(f"[bold green]Enqueued {pushed:,} target URLs into Redis ({settings.redis_start_urls_key})[/]")


def run_web() -> None:
    uvicorn.run(
        "src.web.api:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="leadgen",
        description="DACH 1M-Row Distributed B2B LeadGen, Impressum & Ad-Tech Intelligence CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="Stream 1M+ Handelsregister companies & DACH domains into DuckDB/Parquet")
    p_seed.add_argument("--rows", type=int, default=settings.default_seed_rows, help="Target registry rows (default 1,000,000)")
    p_seed.add_argument("--max-domains", type=int, default=50_000, help="Max DACH commercial domains to extract")
    p_seed.add_argument("--local-bz2", type=str, default="", help="Optional path to local de_companies_ocdata.jsonl.bz2")
    p_seed.add_argument("--no-parquet", action="store_true", help="Skip ZSTD Parquet lakehouse export")
    p_seed.add_argument("--registry-only", action="store_true", help="Seed only Handelsregister companies")
    p_seed.add_argument("--domains-only", action="store_true", help="Seed only Tranco DACH domain frontier")
    p_seed.set_defaults(func=cmd_seed)

    p_crawl = sub.add_parser("crawl", help="Run Scrapy + adaptive curl_cffi crawl sweep")
    p_crawl.add_argument("--limit", type=int, default=100, help="Number of domains to crawl in standalone mode")
    p_crawl.add_argument("--domains", type=str, default="", help="Comma-separated explicit domains to crawl")
    p_crawl.add_argument("--concurrency", type=int, default=settings.concurrent_requests, help="CONCURRENT_REQUESTS")
    p_crawl.add_argument("--redis", action="store_true", help="Consume distributed frontier from Redis (scrapy-redis)")
    p_crawl.add_argument("--force-curl-cffi", action="store_true", help="Route 100%% of traffic through curl_cffi Chrome124")
    p_crawl.add_argument("--export-showcase", action="store_true", help="Export showcase Parquet & CSV after crawl")
    p_crawl.add_argument("--log-level", type=str, default="WARNING", help="Scrapy log level (INFO/WARNING/DEBUG)")
    p_crawl.set_defaults(func=cmd_crawl)

    p_stats = sub.add_parser("stats", help="Display sub-100ms DuckDB OLAP summary over 1M+ rows & crawled leads")
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser("export", help="Export top scored B2B leads to ZSTD Parquet & CSV")
    p_export.add_argument("--limit", type=int, default=5000)
    p_export.set_defaults(func=cmd_export)

    p_redis = sub.add_parser("enqueue-redis", help="Push pending DACH domains from DuckDB into Redis cluster queue")
    p_redis.add_argument("--limit", type=int, default=5000)
    p_redis.set_defaults(func=cmd_enqueue_redis)

    p_web = sub.add_parser("web", help="Launch FastAPI Lead Explorer & Cluster Monitor UI")
    p_web.set_defaults(func=lambda _: run_web())

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
