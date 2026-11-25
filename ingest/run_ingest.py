"""
One ingestion run: API -> Snowflake RAW tables.

    python -m ingest.run_ingest                    full run
    python -m ingest.run_ingest --dry-run          call the API only, print what would load
    python -m ingest.run_ingest --check-snowflake  only test the Snowflake sign-in

GitHub Actions runs the full version every 5 minutes during US market hours.
"""
import argparse
import sys
from datetime import datetime, timezone

from . import config
from .finnhub_client import FinnhubClient


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z  {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-snowflake", action="store_true")
    args = ap.parse_args()

    if args.check_snowflake:
        from .snowflake_loader import connect

        s = config.load(need_snowflake=True)
        with connect(s) as conn:
            row = conn.cursor().execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE()"
            ).fetchone()
        log(f"Snowflake OK  user={row[0]} role={row[1]} warehouse={row[2]} database={row[3]}")
        return 0

    s = config.load(need_snowflake=not args.dry_run)
    api = FinnhubClient(s.finnhub_api_key)

    log(f"Fetching {len(s.tickers)} tickers: {', '.join(s.tickers)}")
    quotes = {t: api.quote(t) for t in s.tickers}
    news = {t: api.company_news(t) for t in s.tickers}

    if args.dry_run:
        for t in s.tickers:
            q = quotes[t]
            log(f"{t:6} price={q.get('c')}  change%={q.get('dp')}  news_articles={len(news[t])}")
        sample = next((a for t in s.tickers for a in news[t]), None)
        if sample:
            log(f"Sample headline: {sample.get('headline')}")
        log("Dry run finished - nothing written to Snowflake.")
        return 0

    from .snowflake_loader import connect, insert_profiles, insert_quotes, merge_news, profiles_due

    with connect(s) as conn:
        n_q = insert_quotes(conn, quotes)
        n_n = merge_news(conn, news)
        n_p = 0
        if profiles_due(conn):
            n_p = insert_profiles(conn, {t: api.profile(t) for t in s.tickers})
    log(f"Loaded quotes={n_q}  new_articles={n_n}  profiles={n_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
