"""
Thin client for the three Finnhub REST endpoints the dashboard uses.

Base URL : https://finnhub.io/api/v1
Auth     : header  X-Finnhub-Token: <your key>   (never put the key in the URL)
Free tier: 60 calls / minute. One run = 2 calls per ticker (+1 per ticker for
           profiles once a day) -> 7 tickers ~ 14-21 calls per run.

Endpoint          What it returns (fields we use)
/quote            c=current price, d=change, dp=change %, h/l/o=day high/low/open,
                  pc=previous close, t=unix time of the quote
/company-news     list of {id, headline, summary, source, url, image, category, datetime}
/stock/profile2   {name, finnhubIndustry, marketCapitalization (USD m),
                   shareOutstanding (m), logo, weburl}
"""
import time
from datetime import date, timedelta

import requests

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    def __init__(self, api_key: str, timeout: int = 15):
        self.session = requests.Session()
        self.session.headers["X-Finnhub-Token"] = api_key
        self.timeout = timeout

    def _get(self, path: str, **params):
        for attempt in range(3):
            resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
            if resp.status_code == 429:  # rate limited: back off and retry
                time.sleep(2 ** attempt * 5)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()

    def quote(self, ticker: str) -> dict:
        return self._get("/quote", symbol=ticker)

    def company_news(self, ticker: str, days_back: int = 2) -> list[dict]:
        today = date.today()
        return self._get(
            "/company-news",
            symbol=ticker,
            **{"from": (today - timedelta(days=days_back)).isoformat(), "to": today.isoformat()},
        ) or []

    def profile(self, ticker: str) -> dict:
        return self._get("/stock/profile2", symbol=ticker) or {}
