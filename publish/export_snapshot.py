"""
Export the MART views to JSON files: the "snapshot" both outputs read.

    python -m publish.export_snapshot --out snapshot

Writes one file per dashboard widget family plus a manifest:

    snapshot/latest_quotes.json      <- MART.V_LATEST_QUOTES     (KPI tiles, table)
    snapshot/price_history.json      <- MART.V_PRICE_HISTORY     (line chart)
    snapshot/news_feed.json          <- MART.V_NEWS_FEED         (news list)
    snapshot/news_volume.json        <- MART.V_NEWS_VOLUME       (bar chart)
    snapshot/pipeline_freshness.json <- MART.V_PIPELINE_FRESHNESS (freshness strip)
    snapshot/manifest.json           when it was made, row counts

Each data file is a JSON array of row objects with lower-case column names.
Timestamps are ISO-8601 strings in UTC; numbers are plain JSON numbers.

In GitHub Actions the folder is then force-pushed to the `data` branch
(see .github/workflows/ingest.yml), so the branch always holds exactly one
commit: the latest snapshot. No history bloat on `main`.
"""
import argparse
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from snowflake.connector import DictCursor

from ingest import config
from ingest.snowflake_loader import connect

EXPORTS = {
    "latest_quotes": "SELECT * FROM TKO_DB.MART.V_LATEST_QUOTES ORDER BY ticker",
    "price_history": "SELECT * FROM TKO_DB.MART.V_PRICE_HISTORY ORDER BY ticker, bucket_5m_utc",
    "news_feed": "SELECT * FROM TKO_DB.MART.V_NEWS_FEED ORDER BY published_at DESC",
    "news_volume": "SELECT * FROM TKO_DB.MART.V_NEWS_VOLUME ORDER BY news_date, ticker",
    "pipeline_freshness": "SELECT * FROM TKO_DB.MART.V_PIPELINE_FRESHNESS ORDER BY feed",
}


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="snapshot")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    s = config.load(need_snowflake=True)

    counts = {}
    with connect(s) as conn:
        for name, sql in EXPORTS.items():
            rows = conn.cursor(DictCursor).execute(sql).fetchall()
            data = [{k.lower(): _clean(v) for k, v in r.items()} for r in rows]
            (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            counts[name] = len(data)

    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Snowflake TKO_DB.MART",
        "tickers": s.tickers,
        "row_counts": counts,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Snapshot written to {out}/  " + "  ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
