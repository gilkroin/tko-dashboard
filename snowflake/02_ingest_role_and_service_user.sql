/* =====================================================================
   TKO Tech-Finance Dashboard — Snowflake setup, part 2
   The WRITE side: a role + a non-human service user for the ingestion job.

   BEFORE RUNNING
   1. On your laptop run:  python scripts/generate_keypair.py
   2. It prints a long public key string. Paste it below in place of
      <PASTE_PUBLIC_KEY_BODY_HERE>  (public key = safe to paste anywhere).

   HOW TO RUN: Snowsight worksheet, role ACCOUNTADMIN, select all, Run All.
   ===================================================================== */

USE ROLE ACCOUNTADMIN;

/* ---------------------------------------------------------------------
   STEP 1 — Ingestion role: may write RAW tables, nothing else.
   SELECT is needed because MERGE reads the table to avoid duplicates.
   --------------------------------------------------------------------- */
CREATE ROLE IF NOT EXISTS TKO_INGESTER
  COMMENT = 'Writes API data into TKO_DB.RAW (used by GitHub Actions)';

GRANT USAGE ON WAREHOUSE TKO_WH    TO ROLE TKO_INGESTER;
GRANT USAGE ON DATABASE  TKO_DB    TO ROLE TKO_INGESTER;
GRANT USAGE ON SCHEMA    TKO_DB.RAW TO ROLE TKO_INGESTER;
GRANT SELECT, INSERT ON ALL TABLES    IN SCHEMA TKO_DB.RAW TO ROLE TKO_INGESTER;
GRANT SELECT, INSERT ON FUTURE TABLES IN SCHEMA TKO_DB.RAW TO ROLE TKO_INGESTER;
GRANT ROLE TKO_INGESTER TO ROLE SYSADMIN;

/* ---------------------------------------------------------------------
   STEP 2 — Service user (TYPE = SERVICE).
   * cannot log in to Snowsight, cannot use a password, no MFA prompts
   * signs in only with the private key that matches RSA_PUBLIC_KEY
   --------------------------------------------------------------------- */
CREATE USER IF NOT EXISTS TKO_INGEST_SVC
  TYPE              = SERVICE
  DEFAULT_ROLE      = TKO_INGESTER
  DEFAULT_WAREHOUSE = TKO_WH
  DEFAULT_NAMESPACE = TKO_DB.RAW
  COMMENT = 'GitHub Actions ingestion job for the TKO dashboard';

ALTER USER TKO_INGEST_SVC SET RSA_PUBLIC_KEY = '<PASTE_PUBLIC_KEY_BODY_HERE>';

GRANT ROLE TKO_INGESTER TO USER TKO_INGEST_SVC;

/* ---------------------------------------------------------------------
   STEP 3 — Check. RSA_PUBLIC_KEY_FP should show a SHA256 fingerprint.
   --------------------------------------------------------------------- */
DESCRIBE USER TKO_INGEST_SVC;
