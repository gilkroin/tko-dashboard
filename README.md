# TKO Tech-Finance Dashboard

A learning project: a live dashboard of tech-company stock prices and financial
news. The data is collected into Snowflake, the code is tracked in Git, and the
dashboard has two outputs: a live Claude dashboard and a static customer webpage.

```
Finnhub REST API ──► ingest/ (Python) ──► Snowflake TKO_DB
 quotes, news,       GitHub Actions          RAW   : API data as received
 profiles            every 5 min, Mon-Fri    MART  : one view per widget
                     13:00-21:59 UTC              │
                                    ┌─────────────┴──────────────┐
                                    ▼                            ▼
                     Claude live dashboard          Customer webpage (GitHub Pages)
                     Snowflake connector, OAuth,    static snapshot, no refresh
                     re-queries every 5 min
                     while it is open
```

## Repository layout

| Path | What it is |
|---|---|
| `snowflake/01_foundation_and_claude_connector.sql` | Warehouse, database, tables, MART views, read-only role, MCP server, OAuth integration for Claude |
| `snowflake/02_ingest_role_and_service_user.sql` | Write role + key-pair service user for the ingestion job |
| `scripts/generate_keypair.py` | Creates the RSA key pair (written to `keys/`, which is git-ignored) |
| `ingest/config.py` | Reads settings from `.env` (laptop) or GitHub secrets (Actions) |
| `ingest/finnhub_client.py` | Finnhub API calls: `/quote`, `/company-news`, `/stock/profile2` |
| `ingest/snowflake_loader.py` | Writes to RAW: appends quotes, MERGEs news (no duplicates), daily profiles |
| `ingest/run_ingest.py` | Entry point: `--dry-run`, `--check-snowflake`, or a full run |
| `.github/workflows/ingest.yml` | The 5-minute schedule |

## Who can access what

| Identity | Authenticates with | Can do | Secret stored in |
|---|---|---|---|
| You (laptop to GitHub) | `gh auth login` browser OAuth | push code, set repo secrets | Windows Credential Manager |
| `TKO_INGEST_SVC` (Snowflake service user) | RSA key pair | INSERT/SELECT on `TKO_DB.RAW` only | `keys/*.p8` on laptop, GitHub secret `SNOWFLAKE_PRIVATE_KEY` |
| Finnhub | API key in header `X-Finnhub-Token` | read market data | `.env`, GitHub secret `FINNHUB_API_KEY` |
| Claude Snowflake connector | OAuth (`TKO_CLAUDE_OAUTH`), your user, role `TKO_DASHBOARD_READER` | read-only SELECT on `TKO_DB.MART` | claude.ai connector token |

Secrets never go into a file that is tracked by Git. `.gitignore` excludes `.env`, `keys/`, `*.p8` and `*.pem`.

## Run locally (Windows PowerShell)

```powershell
cd $HOME\tko-dashboard
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then fill in the values
python -m ingest.run_ingest --dry-run          # API only
python -m ingest.run_ingest --check-snowflake  # sign-in only
python -m ingest.run_ingest                    # full load
```
