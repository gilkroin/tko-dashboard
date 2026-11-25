"""
Writes API results into TKO_DB.RAW.* using the ingestion service user.

Authentication: key-pair (JWT). The connector signs a short-lived token with
the private key; Snowflake verifies it with the public key stored on the user.

Load strategy:
  QUOTES          append every run (it is a time series)
  COMPANY_NEWS    MERGE on (news_id, ticker): an article is stored once,
                  even though every run re-reads the last 2 days of news
  COMPANY_PROFILE append at most once every 20 h
"""
import json
from contextlib import contextmanager

import snowflake.connector
from cryptography.hazmat.primitives import serialization

from .config import Settings

CHUNK = 100  # rows per statement; keeps each SQL text far below Snowflake's 1 MB limit


def _der_private_key(pem: bytes) -> bytes:
    key = serialization.load_pem_private_key(pem, password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@contextmanager
def connect(s: Settings):
    conn = snowflake.connector.connect(
        account=s.sf_account,
        user=s.sf_user,
        private_key=_der_private_key(s.sf_private_key_pem),
        role=s.sf_role,
        warehouse=s.sf_warehouse,
        database=s.sf_database,
        schema="RAW",
        session_parameters={"QUERY_TAG": "tko_ingest"},
    )
    try:
        yield conn
    finally:
        conn.close()


def _values_clause(rows: list[tuple]) -> tuple[str, list]:
    width = len(rows[0])
    one = "(" + ",".join(["%s"] * width) + ")"
    params = [v for row in rows for v in row]
    return ",".join([one] * len(rows)), params


def _chunks(rows, size=CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def insert_quotes(conn, quotes: dict[str, dict]) -> int:
    rows = [
        (t, q.get("c"), q.get("d"), q.get("dp"), q.get("h"), q.get("l"), q.get("o"), q.get("pc"),
         q.get("t"), "finnhub", json.dumps(q))
        for t, q in quotes.items()
        if q and q.get("t")  # t == 0 means unknown symbol / no data
    ]
    if not rows:
        return 0
    values, params = _values_clause(rows)
    conn.cursor().execute(
        f"""
        INSERT INTO QUOTES (ticker, price, change_abs, change_pct, day_high, day_low, day_open,
                            prev_close, quote_ts, source, raw_payload)
        SELECT column1, column2, column3, column4, column5, column6, column7, column8,
               TO_TIMESTAMP_TZ(column9), column10, PARSE_JSON(column11)
        FROM VALUES {values}
        """,
        params,
    )
    return len(rows)


def merge_news(conn, news: dict[str, list[dict]]) -> int:
    rows = [
        (str(a.get("id")), t, a.get("headline"), a.get("summary"), a.get("source"), a.get("url"),
         a.get("image"), a.get("category"), a.get("datetime"), "finnhub", json.dumps(a))
        for t, articles in news.items()
        for a in articles
        if a.get("id") is not None
    ]
    inserted = 0
    for chunk in _chunks(rows):
        values, params = _values_clause(chunk)
        cur = conn.cursor()
        cur.execute(
            f"""
            MERGE INTO COMPANY_NEWS t
            USING (
              SELECT column1 AS news_id, column2 AS ticker, column3 AS headline, column4 AS summary,
                     column5 AS publisher, column6 AS url, column7 AS image_url, column8 AS category,
                     TO_TIMESTAMP_TZ(column9) AS published_at, column10 AS source,
                     PARSE_JSON(column11) AS raw_payload
              FROM VALUES {values}
            ) s
            ON t.news_id = s.news_id AND t.ticker = s.ticker
            WHEN NOT MATCHED THEN INSERT
              (news_id, ticker, headline, summary, publisher, url, image_url, category,
               published_at, source, raw_payload)
            VALUES
              (s.news_id, s.ticker, s.headline, s.summary, s.publisher, s.url, s.image_url, s.category,
               s.published_at, s.source, s.raw_payload)
            """,
            params,
        )
        inserted += cur.fetchone()[0]  # MERGE returns "number of rows inserted"
    return inserted


def profiles_due(conn, max_age_hours: int = 20) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(MAX(ingested_at) < DATEADD('hour', %s, CURRENT_TIMESTAMP()), TRUE) FROM COMPANY_PROFILE",
        (-max_age_hours,),
    )
    return bool(cur.fetchone()[0])


def insert_profiles(conn, profiles: dict[str, dict]) -> int:
    rows = [
        (t, p.get("name"), p.get("finnhubIndustry"), p.get("marketCapitalization"),
         p.get("shareOutstanding"), p.get("logo"), p.get("weburl"), "finnhub", json.dumps(p))
        for t, p in profiles.items()
        if p
    ]
    if not rows:
        return 0
    values, params = _values_clause(rows)
    conn.cursor().execute(
        f"""
        INSERT INTO COMPANY_PROFILE (ticker, company_name, industry, market_cap_musd, shares_out_m,
                                     logo_url, web_url, source, raw_payload)
        SELECT column1, column2, column3, column4, column5, column6, column7, column8, PARSE_JSON(column9)
        FROM VALUES {values}
        """,
        params,
    )
    return len(rows)
