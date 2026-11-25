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
| `.github/workflows/ingest.yml` | The 5-minute schedule: ingest, export snapshot, push it to the `data` branch |
| `snowflake/03_snapshot_export_grants.sql` | Lets the ingestion role read MART views for the export |
| `publish/export_snapshot.py` | MART views → `snapshot/*.json` + `manifest.json` |
| `claude-dashboard/index.html` | Page code of the Claude dashboard (copy kept under version control) |
| `site/shell.html` | Web wrapper: design tokens, d3, and a `dash` adapter that loads `data/*.json` once |
| `publish/build_site.py` | Builds the customer website from the dashboard page and a snapshot |
| `.github/workflows/publish-site.yml` | Publishes the customer website to GitHub Pages (weekdays 22:10 UTC + manual) |

## Why a snapshot instead of live Snowflake queries from Claude

Snowflake trial accounts can't use the Snowflake-managed MCP server that Claude's connector talks to.
So the 5-minute job also exports the MART views as JSON to the `data` branch. A Claude scheduled
task uploads them to the Claude dashboard hourly, and the customer website is built from the same files.
On a paid Snowflake account the Claude dashboard could query `TKO_DB.MART` live instead.

## Preview the customer website locally

```powershell
python -m publish.export_snapshot --out snapshot
python publish/build_site.py --data snapshot --out site/dist
python -m http.server 8000 -d site/dist     # then open http://localhost:8000
```

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
