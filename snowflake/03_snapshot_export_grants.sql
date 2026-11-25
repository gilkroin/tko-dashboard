/* =====================================================================
   TKO Tech-Finance Dashboard — Snowflake setup, part 3
   Lets the ingestion service user READ the MART views, so the same
   GitHub job can export a JSON snapshot after each load.

   Why: on a Snowflake TRIAL account the Snowflake-managed MCP server
   (Claude's live connector) is blocked ("Access denied for trial accounts").
   Instead, GitHub Actions exports MART -> JSON -> `data` branch, and the
   Claude dashboard + customer webpage are built from that snapshot.

   HOW TO RUN: Snowsight worksheet, role ACCOUNTADMIN, select all, Run All.
   ===================================================================== */

USE ROLE ACCOUNTADMIN;

GRANT USAGE  ON SCHEMA TKO_DB.MART                 TO ROLE TKO_INGESTER;
GRANT SELECT ON ALL VIEWS    IN SCHEMA TKO_DB.MART TO ROLE TKO_INGESTER;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA TKO_DB.MART TO ROLE TKO_INGESTER;

-- Check: TKO_INGESTER should now list SELECT on the five MART views.
SHOW GRANTS TO ROLE TKO_INGESTER;
