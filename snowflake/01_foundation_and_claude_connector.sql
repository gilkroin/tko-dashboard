/* =====================================================================
   TKO Tech-Finance Dashboard — Snowflake setup, part 1
   Foundation objects + the Snowflake-managed MCP server that Claude's
   Snowflake connector talks to + the OAuth integration that gives you
   the "OAuth Client ID".

   HOW TO RUN
   1. Sign in to Snowsight (https://app.snowflake.com).
   2. Projects -> Worksheets -> "+" -> SQL Worksheet.
   3. Paste this whole file. Edit the ONE line marked  <<< EDIT >>>.
   4. Top-right role selector: ACCOUNTADMIN.
   5. Run all (Ctrl/Cmd + Shift + Enter). Read the result of the last
      statement: it contains your OAuth Client ID.

   Re-running is safe: every statement is CREATE ... IF NOT EXISTS or
   CREATE OR REPLACE.
   ===================================================================== */

USE ROLE ACCOUNTADMIN;

-- <<< EDIT >>>  your Snowflake login name, in UPPER CASE (Snowsight: bottom-left -> your name -> Profile)
SET my_user = 'YOUR_SNOWFLAKE_USERNAME';


/* ---------------------------------------------------------------------
   STEP 1 — Compute: one X-Small warehouse that sleeps after 60 s idle.
   Cost lever #1: AUTO_SUSPEND = 60 means you only pay while queries run
   (minimum 60 s billed each time it wakes up).
   --------------------------------------------------------------------- */
CREATE WAREHOUSE IF NOT EXISTS TKO_WH
  WAREHOUSE_SIZE      = 'XSMALL'
  AUTO_SUSPEND        = 60
  AUTO_RESUME         = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'TKO dashboard: ingestion + dashboard queries';

/* Cost lever #2: a resource monitor that emails you at 75 % and
   suspends the warehouse at 100 % of a monthly credit budget.
   40 credits/month is a comfortable ceiling for 5-min ingestion during
   US market hours. Change it to suit your budget.                     */
CREATE RESOURCE MONITOR IF NOT EXISTS TKO_MONTHLY_CAP
  WITH CREDIT_QUOTA = 40
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 75  PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE TKO_WH SET RESOURCE_MONITOR = TKO_MONTHLY_CAP;


/* ---------------------------------------------------------------------
   STEP 2 — Storage layout (medallion style)
     RAW  : exactly what the APIs returned (append-only, audit trail)
     CORE : cleaned / de-duplicated
     MART : views shaped for each dashboard widget  <- dashboard reads ONLY this
     APP  : holds the MCP server object for Claude
   --------------------------------------------------------------------- */
CREATE DATABASE IF NOT EXISTS TKO_DB COMMENT = 'TKO tech-finance dashboard';
CREATE SCHEMA IF NOT EXISTS TKO_DB.RAW;
CREATE SCHEMA IF NOT EXISTS TKO_DB.CORE;
CREATE SCHEMA IF NOT EXISTS TKO_DB.MART;
CREATE SCHEMA IF NOT EXISTS TKO_DB.APP;


/* ---------------------------------------------------------------------
   STEP 3 — Raw tables the ingestion job (Stage 4) will append to.
   --------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS TKO_DB.RAW.QUOTES (
  ticker         STRING        NOT NULL,
  price          NUMBER(18,4),            -- current / last price
  change_abs     NUMBER(18,4),            -- vs previous close
  change_pct     NUMBER(10,4),
  day_high       NUMBER(18,4),
  day_low        NUMBER(18,4),
  day_open       NUMBER(18,4),
  prev_close     NUMBER(18,4),
  quote_ts       TIMESTAMP_TZ,            -- time the exchange quote refers to
  source         STRING,                  -- e.g. 'finnhub'
  ingested_at    TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  raw_payload    VARIANT                  -- full API response, for audit / replays
);

CREATE TABLE IF NOT EXISTS TKO_DB.RAW.COMPANY_NEWS (
  news_id        STRING        NOT NULL,  -- provider's article id
  ticker         STRING        NOT NULL,
  headline       STRING,
  summary        STRING,
  publisher      STRING,
  url            STRING,
  image_url      STRING,
  category       STRING,
  published_at   TIMESTAMP_TZ,
  source         STRING,
  ingested_at    TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  raw_payload    VARIANT
);

CREATE TABLE IF NOT EXISTS TKO_DB.RAW.COMPANY_PROFILE (
  ticker         STRING        NOT NULL,
  company_name   STRING,
  industry       STRING,
  market_cap_musd NUMBER(20,2),
  shares_out_m   NUMBER(20,4),
  logo_url       STRING,
  web_url        STRING,
  source         STRING,
  ingested_at    TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  raw_payload    VARIANT
);


/* ---------------------------------------------------------------------
   STEP 4 — MART views: one per dashboard widget family.
   The dashboard never touches RAW; if a widget changes, only its view
   changes.
   --------------------------------------------------------------------- */

-- KPI tiles: latest quote per ticker
CREATE OR REPLACE VIEW TKO_DB.MART.V_LATEST_QUOTES AS
SELECT q.ticker, p.company_name, q.price, q.change_abs, q.change_pct,
       q.day_high, q.day_low, q.day_open, q.prev_close, q.quote_ts, q.ingested_at
FROM TKO_DB.RAW.QUOTES q
LEFT JOIN (
  SELECT * FROM TKO_DB.RAW.COMPANY_PROFILE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY ingested_at DESC) = 1
) p USING (ticker)
QUALIFY ROW_NUMBER() OVER (PARTITION BY q.ticker ORDER BY q.ingested_at DESC) = 1;

-- Line chart: intraday price path, 5-min points, last 5 days
-- TIME_SLICE does not accept TIMESTAMP_TZ, so convert to UTC wall-clock
-- time (TIMESTAMP_NTZ) first. All dashboard times are therefore in UTC.
CREATE OR REPLACE VIEW TKO_DB.MART.V_PRICE_HISTORY AS
SELECT ticker,
       TIME_SLICE(CONVERT_TIMEZONE('UTC', ingested_at)::TIMESTAMP_NTZ, 5, 'MINUTE') AS bucket_5m_utc,
       AVG(price)      AS price,
       AVG(change_pct) AS change_pct
FROM TKO_DB.RAW.QUOTES
WHERE ingested_at >= DATEADD('day', -5, CURRENT_TIMESTAMP())
GROUP BY 1, 2;

-- News feed (qualitative): newest 200 unique articles
CREATE OR REPLACE VIEW TKO_DB.MART.V_NEWS_FEED AS
SELECT news_id, ticker, headline, summary, publisher, url, category, published_at
FROM TKO_DB.RAW.COMPANY_NEWS
QUALIFY ROW_NUMBER() OVER (PARTITION BY news_id, ticker ORDER BY ingested_at DESC) = 1
ORDER BY published_at DESC
LIMIT 200;

-- Bar chart: news volume per ticker per day (attention indicator)
CREATE OR REPLACE VIEW TKO_DB.MART.V_NEWS_VOLUME AS
SELECT ticker, DATE(published_at) AS news_date, COUNT(DISTINCT news_id) AS articles
FROM TKO_DB.RAW.COMPANY_NEWS
WHERE published_at >= DATEADD('day', -14, CURRENT_TIMESTAMP())
GROUP BY 1, 2;

-- Freshness widget: when did each feed last land?
CREATE OR REPLACE VIEW TKO_DB.MART.V_PIPELINE_FRESHNESS AS
SELECT 'quotes' AS feed, MAX(ingested_at) AS last_loaded_at, COUNT(*) AS rows_total FROM TKO_DB.RAW.QUOTES
UNION ALL
SELECT 'news',   MAX(ingested_at), COUNT(*) FROM TKO_DB.RAW.COMPANY_NEWS
UNION ALL
SELECT 'profiles', MAX(ingested_at), COUNT(*) FROM TKO_DB.RAW.COMPANY_PROFILE;


/* ---------------------------------------------------------------------
   STEP 5 — Least-privilege READ role for Claude.
   It can read MART views and nothing else. It can never write.
   --------------------------------------------------------------------- */
CREATE ROLE IF NOT EXISTS TKO_DASHBOARD_READER
  COMMENT = 'Read-only role used by the Claude Snowflake connector';

GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE TKO_DASHBOARD_READER;
GRANT USAGE ON WAREHOUSE TKO_WH          TO ROLE TKO_DASHBOARD_READER;
GRANT USAGE ON DATABASE  TKO_DB          TO ROLE TKO_DASHBOARD_READER;
GRANT USAGE ON SCHEMA    TKO_DB.MART     TO ROLE TKO_DASHBOARD_READER;
GRANT USAGE ON SCHEMA    TKO_DB.APP      TO ROLE TKO_DASHBOARD_READER;
GRANT SELECT ON ALL VIEWS    IN SCHEMA TKO_DB.MART TO ROLE TKO_DASHBOARD_READER;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA TKO_DB.MART TO ROLE TKO_DASHBOARD_READER;

-- Keep the role hierarchy tidy: SYSADMIN inherits it.
GRANT ROLE TKO_DASHBOARD_READER TO ROLE SYSADMIN;
GRANT ROLE TKO_DASHBOARD_READER TO USER IDENTIFIER($my_user);


/* ---------------------------------------------------------------------
   STEP 6 — The Snowflake-managed MCP server.
   This is the endpoint Claude's connector calls. It exposes ONE tool:
   read-only SQL, executed with the caller's role (TKO_DASHBOARD_READER).
   NOTE: CREATE OR REPLACE drops grants, so the GRANT follows right after.
   --------------------------------------------------------------------- */
CREATE OR REPLACE MCP SERVER TKO_DB.APP.TKO_MCP
  FROM SPECIFICATION $$
  tools:
    - title: "TKO read-only SQL"
      name: "tko_sql"
      type: "SYSTEM_EXECUTE_SQL"
      description: "Read-only SQL over TKO_DB.MART views: V_LATEST_QUOTES, V_PRICE_HISTORY, V_NEWS_FEED, V_NEWS_VOLUME, V_PIPELINE_FRESHNESS."
      config:
        read_only: true
        query_timeout: 120
        warehouse: "TKO_WH"
  $$;

GRANT USAGE ON MCP SERVER TKO_DB.APP.TKO_MCP TO ROLE TKO_DASHBOARD_READER;


/* ---------------------------------------------------------------------
   STEP 7 — OAuth security integration = where the Client ID comes from.
   PUBLIC client type: Claude uses PKCE, so no client secret is needed.
   Redirect URI must match EXACTLY what Claude shows during connector setup.
   --------------------------------------------------------------------- */
CREATE OR REPLACE SECURITY INTEGRATION TKO_CLAUDE_OAUTH
  TYPE                      = OAUTH
  OAUTH_CLIENT              = CUSTOM
  ENABLED                   = TRUE
  OAUTH_CLIENT_TYPE         = 'PUBLIC'
  OAUTH_REDIRECT_URI        = 'https://claude.ai/api/mcp/auth_callback'
  OAUTH_USE_SECONDARY_ROLES = NONE
  ALLOWED_ROLES_LIST        = ('TKO_DASHBOARD_READER')
  COMMENT = 'Claude.ai Snowflake connector for the TKO dashboard';


/* ---------------------------------------------------------------------
   STEP 8 — MCP sessions start in your DEFAULT_ROLE and need a DEFAULT_WAREHOUSE.
   OAuth also refuses ACCOUNTADMIN / SECURITYADMIN sessions, so the default
   must be the reader role. In Snowsight you can still switch to
   ACCOUNTADMIN with the role picker whenever you need it.
   --------------------------------------------------------------------- */
ALTER USER IDENTIFIER($my_user) SET
  DEFAULT_ROLE      = 'TKO_DASHBOARD_READER'
  DEFAULT_WAREHOUSE = 'TKO_WH';


/* ---------------------------------------------------------------------
   STEP 9 — Show the connection details.
   ---------------------------------------------------------------------
   OAUTH_CLIENT_ID is in the JSON output. Copy only OAUTH_CLIENT_ID into
   Claude's connector form. Do NOT paste anything else from it into chat.
   --------------------------------------------------------------------- */
SELECT SYSTEM$SHOW_OAUTH_CLIENT_SECRETS('TKO_CLAUDE_OAUTH');

-- Your account identifier, for building the server URL:
SELECT LOWER(CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME()) AS account_identifier;
/* MCP server URL  (replace any "_" with "-" in the identifier):
   https://<account_identifier>.snowflakecomputing.com/api/v2/databases/TKO_DB/schemas/APP/mcp-servers/TKO_MCP
*/
