"""Fetch SUUMO rental search result pages and save listings as JSON.

Default target is a Tokyo rental listing search. Each building (cassetteitem)
contains one or more rooms; the script flattens them into a single list of
room records with building-level fields duplicated. Output is written to
`data/001_fetch_suumo/listings.json`.
"""

import json
import re
import time
import urllib.parse
from pathlib import Path

import click
from bs4 import BeautifulSoup, Tag
from curl_cffi import requests
from proxy import dataimpulse_rotating_proxy_url

DEFAULT_URL = "https://suumo.jp/jj/chintai/ichiran/FR301FC001/?ar=030&bs=040&ta=13"
DETAIL_URL_BASE = "https://suumo.jp"
LISTING_ID_PATTERN = re.compile(r"/chintai/(jnc_\d+)/")
IMPERSONATE_TARGET = "safari18_0"
REQUEST_TIMEOUT_SECONDS = 30.0
SLEEP_BETWEEN_REQUESTS_SECONDS = 2.0
SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent.parent / "data" / SCRIPT_PATH.stem


def build_page_url(base_url: str, page: int) -> str:
    """Return `base_url` with `page=<n>` set in the query string."""
    parsed = urllib.parse.urlparse(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


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


@click.command()
@click.option("--url", default=DEFAULT_URL, show_default=True, help="SUUMO search URL.")
@click.option("--pages", default=1, show_default=True, type=int, help="Number of pages to fetch.")
def main(url: str, pages: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    listings: list[dict] = []

    for page in range(1, pages + 1):
        page_url = build_page_url(url, page)
        proxy_url = dataimpulse_rotating_proxy_url()
        print(f"[{page}/{pages}] GET {page_url}")
        with requests.Session(
            impersonate=IMPERSONATE_TARGET,
            timeout=REQUEST_TIMEOUT_SECONDS,
            proxies={"http": proxy_url, "https": proxy_url},
        ) as session:
            response = session.get(page_url)
        response.raise_for_status()
        page_records = parse_page(response.text)
        for record in page_records:
            record["source_page"] = page
        listings.extend(page_records)
        print(f"  -> {response.status_code}, parsed {len(page_records)} rooms")
        if page < pages:
            time.sleep(SLEEP_BETWEEN_REQUESTS_SECONDS)

    output_path = OUTPUT_DIR / "listings.json"
    output_path.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(listings)} listings to {output_path}")


if __name__ == "__main__":
    main()
