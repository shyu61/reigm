"""Fetch SUUMO rental search result pages and stream listings as JSONL.

Default target is a Tokyo rental listing search. Each building (cassetteitem)
contains one or more rooms; the script flattens them into a single record per
room with building-level fields duplicated. Records are appended to
`data/001_fetch_suumo/listings.jsonl` and flushed after each page, so an
interrupted run (network drop, SIGINT) preserves everything fetched so far.
"""

import json
import re
import urllib.parse
from pathlib import Path

import click
from bs4 import BeautifulSoup, Tag
from curl_cffi import requests
from proxy import dataimpulse_rotating_proxy_url
from utils import jitter_sleep

DEFAULT_URL = (
    "https://suumo.jp/jj/chintai/ichiran/FR301FC001/?ar=030&bs=040&ta=13"
    "&sc=13101&sc=13102&sc=13103&sc=13104&sc=13105&sc=13106&sc=13107&sc=13108"
    "&sc=13109&sc=13110&sc=13111&sc=13112&sc=13113&sc=13114&sc=13115&sc=13116"
    "&sc=13117&sc=13118&sc=13119&sc=13120&sc=13121&sc=13122&sc=13123"
)
DETAIL_URL_BASE = "https://suumo.jp"
LISTING_ID_PATTERN = re.compile(r"/chintai/(jnc_\d+)/")
IMPERSONATE_TARGET = "safari18_0"
REQUEST_TIMEOUT_SECONDS = 30.0
SLEEP_MIN_SECONDS = 2.0
SLEEP_MAX_SECONDS = 5.0
SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent.parent / "data" / SCRIPT_PATH.stem


def build_page_url(base_url: str, page: int) -> str:
    """Return `base_url` with `page=<n>` set in the query string."""
    parsed = urllib.parse.urlparse(base_url)
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if k != "page"]
    pairs.append(("page", str(page)))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(pairs)))


def _text(node: Tag | None) -> str:
    return node.get_text(strip=True) if node else ""


def parse_building(building: Tag) -> dict:
    """Extract building-level (cassetteitem) fields shared by all its rooms."""
    detail_cols = building.select_one(".cassetteitem_detail")
    age_floors = detail_cols.select(".cassetteitem_detail-col3 div") if detail_cols else []
    return {
        "category": _text(building.select_one(".cassetteitem_content-label")),
        "title": _text(building.select_one(".cassetteitem_content-title")),
        "address": _text(building.select_one(".cassetteitem_detail-col1")),
        "access": [
            _text(t) for t in building.select(".cassetteitem_detail-col2 .cassetteitem_detail-text") if _text(t)
        ],
        "age": _text(age_floors[0]) if len(age_floors) > 0 else "",
        "structure": _text(age_floors[1]) if len(age_floors) > 1 else "",
    }


def parse_room(row: Tag) -> dict:
    """Extract room-level fields from a single tbody row."""
    cells = row.find_all("td", recursive=False)
    floor = _text(cells[2]) if len(cells) > 2 else ""
    detail_link = row.select_one("a.js-cassette_link_href")
    detail_href = detail_link.get("href", "") if detail_link else ""
    listing_match = LISTING_ID_PATTERN.search(detail_href)
    room_input = row.select_one("input.js-clipkey")
    return {
        "listing_id": listing_match.group(1) if listing_match else "",
        "room_id": room_input.get("value", "") if room_input else "",
        "floor": floor,
        "rent": _text(row.select_one(".cassetteitem_price--rent")),
        "admin_fee": _text(row.select_one(".cassetteitem_price--administration")),
        "deposit": _text(row.select_one(".cassetteitem_price--deposit")),
        "gratuity": _text(row.select_one(".cassetteitem_price--gratuity")),
        "layout": _text(row.select_one(".cassetteitem_madori")),
        "area": _text(row.select_one(".cassetteitem_menseki")),
        "detail_url": urllib.parse.urljoin(DETAIL_URL_BASE, detail_href) if detail_href else "",
    }


def parse_page(html: str) -> list[dict]:
    """Flatten all (building, room) pairs in `html` into one list of records."""
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    for building in soup.select(".cassetteitem"):
        building_fields = parse_building(building)
        for row in building.select("tbody tr.js-cassette_link"):
            records.append({**building_fields, **parse_room(row)})
    return records


def fetch_page(url: str) -> str:
    """Fetch one URL through a fresh DataImpulse session (rotates exit IP)."""
    proxy_url = dataimpulse_rotating_proxy_url()
    with requests.Session(
        impersonate=IMPERSONATE_TARGET,
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies={"http": proxy_url, "https": proxy_url},
    ) as session:
        response = session.get(url)
    response.raise_for_status()
    return response.text


def latest_fetched_page(jsonl_path: Path) -> int:
    """Return the largest `source_page` already in `jsonl_path`, or 0 if missing/empty."""
    if not jsonl_path.exists():
        return 0
    latest = 0
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            page = json.loads(line).get("source_page", 0)
            if page > latest:
                latest = page
    return latest


@click.command()
@click.option("--url", default=DEFAULT_URL, show_default=True, help="SUUMO search URL.")
@click.option("--pages", default=1, show_default=True, type=int, help="Number of pages to fetch.")
def main(url: str, pages: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "listings.jsonl"
    start_page = latest_fetched_page(output_path) + 1
    last_page = start_page + pages - 1
    total_records = 0
    failed_pages: list[int] = []
    print(f"Resuming from page {start_page} (writing to {output_path})")

    with output_path.open("a", encoding="utf-8") as out:
        for page in range(start_page, last_page + 1):
            page_url = build_page_url(url, page)
            print(f"[page {page}/{last_page}] GET {page_url}")
            try:
                html = fetch_page(page_url)
            except Exception as exc:
                print(f"  ! fetch failed: {exc!r}")
                failed_pages.append(page)
            else:
                page_records = parse_page(html)
                for record in page_records:
                    record["source_page"] = page
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                total_records += len(page_records)
                print(f"  -> parsed {len(page_records)} rooms (total {total_records})")
            if page < last_page:
                delay = jitter_sleep(SLEEP_MIN_SECONDS, SLEEP_MAX_SECONDS)
                print(f"  slept {delay:.2f}s")

    print(f"Wrote {total_records} listings to {output_path}")
    if failed_pages:
        print(f"Failed pages ({len(failed_pages)}): {failed_pages}")


if __name__ == "__main__":
    main()
