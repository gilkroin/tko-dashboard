"""
Reads all settings from environment variables.

Locally they come from the .env file (loaded by python-dotenv).
In GitHub Actions they come from encrypted repository secrets / variables.
The code never contains a secret itself.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing setting {name}. Add it to .env (local) or GitHub secrets (Actions).")
    return value


@dataclass(frozen=True)
class Settings:
    finnhub_api_key: str
    tickers: list[str]
    sf_account: str
    sf_user: str
    sf_role: str
    sf_warehouse: str
    sf_database: str
    sf_private_key_pem: bytes


def _private_key_pem() -> bytes:
    # GitHub Actions: key content in SNOWFLAKE_PRIVATE_KEY
    content = os.getenv("SNOWFLAKE_PRIVATE_KEY", "").strip()
    if content:
        return content.encode()
    # Laptop: path to the .p8 file
    path = Path(_req("SNOWFLAKE_PRIVATE_KEY_PATH"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path.read_bytes()


def load(need_snowflake: bool = True) -> Settings:
    tickers = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA").split(",") if t.strip()]
    return Settings(
        finnhub_api_key=_req("FINNHUB_API_KEY"),
        tickers=tickers,
        sf_account=_req("SNOWFLAKE_ACCOUNT") if need_snowflake else "",
        sf_user=os.getenv("SNOWFLAKE_USER", "TKO_INGEST_SVC"),
        sf_role=os.getenv("SNOWFLAKE_ROLE", "TKO_INGESTER"),
        sf_warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "TKO_WH"),
        sf_database=os.getenv("SNOWFLAKE_DATABASE", "TKO_DB"),
        sf_private_key_pem=_private_key_pem() if need_snowflake else b"",
    )
