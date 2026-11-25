"""
Build the customer-facing static website from a data snapshot.

    python publish/build_site.py --data snapshot --out site/dist

Inputs
  claude-dashboard/index.html  the SAME page code the Claude dashboard runs
  site/shell.html              HTML wrapper: design tokens, d3, and a small
                               `dash` adapter that loads data/*.json once
  --data <folder>              a snapshot folder (manifest.json + 5 JSON files),
                               e.g. the local `snapshot/` or the `data` branch

Output (--out)
  index.html                   self-contained page, no auto-refresh
  data/*.json                  copies of the snapshot files

Only standard-library Python, so the GitHub Pages job needs no pip install.
"""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["latest_quotes", "price_history", "news_feed", "news_volume", "pipeline_freshness"]

# Wording that is true for the live Claude dashboard but not for a frozen snapshot.
REPLACEMENTS = [
    (
        "Prices come from Finnhub every 5 minutes during US market hours; this dashboard's copy is refreshed hourly.",
        "This page is a published snapshot ({label}) and does not update while it is open.",
    ),
    (
        "<li>A Claude scheduled task uploads the newest JSON files to this dashboard once an hour.</li>",
        "<li>A separate job publishes a snapshot of those files as this web page after the US market closes.</li>",
    ),
    (
        "Open Sources to see the file behind every number.",
        "The data behind every number is linked in the footer.",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="site/dist")
    args = ap.parse_args()

    data_dir, out = Path(args.data), Path(args.out)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    ts = datetime.strptime(manifest["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    label = ts.strftime("%d %b %Y, %H:%M UTC")

    page = (ROOT / "claude-dashboard" / "index.html").read_text(encoding="utf-8")
    # The two <meta> lines only matter inside Claude's dashboard editor.
    page = "\n".join(l for l in page.splitlines() if not l.startswith('<meta name="dash-'))
    for old, new in REPLACEMENTS:
        if old not in page:
            raise SystemExit(f"build_site: expected text not found in dashboard page:\n  {old}")
        page = page.replace(old, new.format(label=label))

    shell = (ROOT / "site" / "shell.html").read_text(encoding="utf-8")
    html = shell.replace("{{DASHBOARD}}", page).replace("{{SNAPSHOT_LABEL}}", label)

    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    for name in FILES + ["manifest"]:
        shutil.copy2(data_dir / f"{name}.json", out / "data" / f"{name}.json")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is on GitHub Pages
    print(f"Site built in {out}/  (snapshot {label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
