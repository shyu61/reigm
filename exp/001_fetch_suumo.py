"""Fetch SUUMO rental search result pages and save raw HTML.

Default target is a Tokyo (23-ku) rental listing page. Each fetched page is
saved as `page_{n:03d}.html` under `data/001_fetch_suumo/`. A small JSON
manifest records the URL, status code, and byte size for each page.
"""

import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import click
import httpx

DEFAULT_URL = "https://suumo.jp/jj/chintai/ichiran/FR301FC001/?ar=030&bs=040&ta=13"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 30.0
SLEEP_BETWEEN_REQUESTS_SECONDS = 2.0
SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent.parent / "data" / SCRIPT_PATH.stem


def build_page_url(base_url: str, page: int) -> str:
    """Return `base_url` with `page=<n>` appended to the query string."""
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query)))


@click.command()
@click.option("--url", default=DEFAULT_URL, show_default=True, help="SUUMO search URL.")
@click.option("--pages", default=1, show_default=True, type=int, help="Number of pages to fetch.")
def main(url: str, pages: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"}
    manifest: list[dict] = []

    with httpx.Client(headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            page_url = build_page_url(url, page)
            print(f"[{page}/{pages}] GET {page_url}")
            response = client.get(page_url)
            html_path = OUTPUT_DIR / f"page_{page:03d}.html"
            html_path.write_text(response.text, encoding="utf-8")
            manifest.append(
                {
                    "page": page,
                    "url": page_url,
                    "status": response.status_code,
                    "bytes": len(response.content),
                    "file": html_path.name,
                }
            )
            print(f"  -> {response.status_code}, {len(response.content)} bytes -> {html_path}")
            if page < pages:
                time.sleep(SLEEP_BETWEEN_REQUESTS_SECONDS)

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote manifest to {manifest_path}")


if __name__ == "__main__":
    main()
