"""Smoke test for the Google Maps API calls used in walking-time analysis.

Exercises three calls end-to-end on a tiny sample (default 2 buildings) so the
total spend stays trivially inside the free monthly caps:

  1. Building geocoding via the cheap 2-step path:
       - Places Text Search (New), IDs Only         → free / unlimited
       - Place Details (New), fields=location,...   → Essentials, $5/1k (10k free)
  2. Station geocoding via Geocoding API            → Essentials, $5/1k (10k free)
  3. Walking duration via Routes API Compute        → Essentials, $5/1k elements
     Route Matrix (travelMode: WALK)                  (10k free)

Input is `data/001_fetch_suumo/listings.jsonl` plus a hardcoded SAMPLE_BUILDINGS
list (used first, useful for ad-hoc probes of buildings not in the listings).
Picks the first N unique (title, address) buildings that have >=2 walk-only
access entries with stated time <=20min, and uses '{title} {address}' as the
Places Text Search query (listings.jsonl has no lat/lon). Prints every
request/response and writes a per-(building, station) CSV with stated vs.
actual walking minutes and signed error (stated/error are blank for hardcoded
samples without known stated walk times).

Required: GOOGLE_MAPS_API_KEY in `.env`, with these APIs enabled in GCP:
  Places API (New), Geocoding API, Routes API.
"""

import csv
import json
import re
import unicodedata
from pathlib import Path

import click
import httpx

from settings import settings

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
OUTPUT_CSV = OUTPUT_DIR / "test_results.csv"

# Skip titles that are really listing blurbs rather than building names — Places
# Text Search has nothing to resolve in those (e.g.
# "西武池袋線 石神井公園駅 徒歩6分 敷礼無 角部屋 防犯カメラ有").
DESCRIPTIVE_TITLE_RE = re.compile(
    r"駅\s.*階建|築\d+年|戸建|貸家|借家|賃貸|貸マンション|共同住宅|倉庫|店舗|事務所"
    r"|徒歩\d+分|敷礼|角部屋|防犯カメラ|オートロック|宅配ボックス|エレベーター|ペット(?:可|相談)|駐車場"
)

DEFAULT_N_BUILDINGS = 2
MAX_N_BUILDINGS = 10  # hard cap so this test can't accidentally rack up cost
WALK_CUTOFF_MIN = 20

# Hardcoded samples (not in listings.jsonl). stated_min=None means we skip the
# stated-vs-actual comparison and only record the API-measured walking time.
SAMPLE_BUILDINGS: list[dict] = [
    {
        "title": "AZURE三宿",
        "address": "東京都世田谷区三宿1",
        "stations": [("池尻大橋駅", None), ("三軒茶屋駅", None)],
    },
]

WALK_RE = re.compile(r"歩(\d+)分")
REQUEST_TIMEOUT = 30.0

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL_TEMPLATE = "https://places.googleapis.com/v1/places/{place_id}"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTE_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

# Rough bbox covering Tokyo 23-ku, used to bias Geocoding API results.
TOKYO_BOUNDS = "35.50,139.55|35.85,139.95"


def _parse_station(entry: str) -> str | None:
    if "/" not in entry:
        return None
    return entry.split("/", 1)[1].split(" ", 1)[0]


def _is_descriptive_title(raw: str) -> bool:
    return bool(DESCRIPTIVE_TITLE_RE.search(unicodedata.normalize("NFKC", raw)))


def _pick_test_buildings(path: Path, n: int) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    picked: list[dict] = [dict(b) for b in SAMPLE_BUILDINGS[:n]]
    for b in picked:
        seen.add((b["title"], b["address"]))
    if len(picked) >= n:
        print(f"using {len(picked)} hardcoded sample building(s); skipping listings pick")
        return picked
    skipped_descriptive = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            title, address = r.get("title"), r.get("address")
            if not title or not address:
                continue
            key = (title, address)
            if key in seen:
                continue
            if _is_descriptive_title(title):
                skipped_descriptive += 1
                seen.add(key)
                continue
            entries: list[tuple[str, int]] = []
            for entry in r.get("access") or []:
                if "バス" in entry:
                    continue
                station = _parse_station(entry)
                match = WALK_RE.search(entry)
                if not station or not match:
                    continue
                mins = int(match.group(1))
                if mins <= WALK_CUTOFF_MIN:
                    entries.append((station, mins))
            if len(entries) < 2:
                continue
            seen.add(key)
            picked.append({"title": title, "address": address, "stations": entries})
            if len(picked) >= n:
                break
    print(f"skipped {skipped_descriptive} descriptive-title buildings while picking")
    return picked


def _check(r: httpx.Response, label: str) -> None:
    if r.is_success:
        return
    print(f"    !! {label} HTTP {r.status_code}: {r.text[:400]}")
    r.raise_for_status()


def _places_text_search_id(client: httpx.Client, query: str, key: str) -> str | None:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id",
    }
    body = {
        "textQuery": query,
        "languageCode": "ja",
        "regionCode": "JP",
        "maxResultCount": 1,
    }
    print(f"  [TextSearch IDs-only] query={query!r}")
    r = client.post(PLACES_TEXT_SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    _check(r, "TextSearch")
    places = r.json().get("places") or []
    if not places:
        print("    -> no place candidates")
        return None
    pid = places[0].get("id")
    print(f"    -> place_id={pid}")
    return pid


def _place_details_essentials(client: httpx.Client, place_id: str, key: str) -> dict | None:
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "location,formattedAddress,types",
    }
    url = PLACE_DETAILS_URL_TEMPLATE.format(place_id=place_id)
    print(f"  [PlaceDetails Essentials] place_id={place_id}")
    r = client.get(url, headers=headers, params={"languageCode": "ja"}, timeout=REQUEST_TIMEOUT)
    _check(r, "PlaceDetails")
    data = r.json()
    loc = data.get("location")
    if not loc:
        print(f"    -> no location in response: {data}")
        return None
    out = {
        "lat": loc["latitude"],
        "lon": loc["longitude"],
        "formatted_address": data.get("formattedAddress"),
        "types": data.get("types") or [],
    }
    print(f"    -> lat={out['lat']:.6f} lon={out['lon']:.6f}")
    print(f"       formattedAddress={out['formatted_address']}")
    print(f"       types={out['types']}")
    return out


def _geocode_station(client: httpx.Client, name: str, key: str) -> dict | None:
    params = {
        "address": name,
        "region": "jp",
        "language": "ja",
        "components": "country:JP",
        "bounds": TOKYO_BOUNDS,
        "key": key,
    }
    print(f"  [Geocode] address={name!r}")
    r = client.get(GEOCODE_URL, params=params, timeout=REQUEST_TIMEOUT)
    _check(r, "Geocode")
    data = r.json()
    results = data.get("results") or []
    if data.get("status") != "OK" or not results:
        print(f"    -> status={data.get('status')} no results")
        return None
    g = results[0]
    loc = g["geometry"]["location"]
    out = {
        "lat": loc["lat"],
        "lon": loc["lng"],
        "place_id": g.get("place_id"),
        "formatted_address": g.get("formatted_address"),
    }
    print(f"    -> lat={out['lat']:.6f} lon={out['lon']:.6f}  place_id={out['place_id']}  {out['formatted_address']}")
    return out


def _route_matrix_walk(
    client: httpx.Client,
    origin: tuple[float, float],
    destination_place_ids: list[str],
    key: str,
) -> list[dict]:
    """Compute walking durations from a building origin (latLng) to station destinations (placeId).

    Stations use placeId waypoints so the Routes API can route to a known access point
    of the station rather than snapping the centroid lat/lon to the nearest road, which
    often lands on the wrong side of the tracks for large stations.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,condition",
    }
    body = {
        "origins": [{"waypoint": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}}}],
        "destinations": [{"waypoint": {"placeId": pid}} for pid in destination_place_ids],
        "travelMode": "WALK",
    }
    print(
        f"  [RouteMatrix WALK] 1 origin x {len(destination_place_ids)} destinations "
        f"= {len(destination_place_ids)} elements (destinations via placeId)"
    )
    r = client.post(ROUTE_MATRIX_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    _check(r, "RouteMatrix")
    out: list[dict] = []
    for row in r.json():
        dur = row.get("duration", "0s")
        try:
            duration_s = float(dur.rstrip("s"))
        except ValueError:
            duration_s = 0.0
        out.append(
            {
                "dest_idx": row.get("destinationIndex", 0),
                "duration_s": duration_s,
                "distance_m": row.get("distanceMeters"),
                "condition": row.get("condition"),
            }
        )
    for o in out:
        print(
            f"    -> dest={o['dest_idx']}  {o['duration_s']:.0f}s "
            f"({o['duration_s'] / 60:.1f}min)  {o['distance_m']}m  cond={o['condition']}"
        )
    return out


@click.command()
@click.option(
    "--n-buildings",
    type=int,
    default=DEFAULT_N_BUILDINGS,
    show_default=True,
    help=f"Number of buildings to test (hard-capped at {MAX_N_BUILDINGS} for cost safety).",
)
def main(n_buildings: int) -> None:
    if n_buildings < 1 or n_buildings > MAX_N_BUILDINGS:
        raise click.ClickException(f"--n-buildings must be between 1 and {MAX_N_BUILDINGS}.")

    key = settings.google_maps_api_key
    if not key:
        raise click.ClickException(
            "GOOGLE_MAPS_API_KEY is not set in .env. Enable in GCP: Places API (New), Geocoding API, Routes API."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    buildings = _pick_test_buildings(LISTINGS_PATH, n_buildings)
    print(f"picked {len(buildings)} test buildings\n")

    rows: list[dict] = []
    api_calls = {"text_search": 0, "place_details": 0, "geocode": 0, "route_matrix_elements": 0}

    with httpx.Client() as client:
        for b in buildings:
            title, address, stations = b["title"], b["address"], b["stations"]
            print(f"=== Building: {title} | {address} ===")

            pid = _places_text_search_id(client, f"{title} {address}", key)
            api_calls["text_search"] += 1
            if not pid:
                print("  -> drop building (Places no match)\n")
                continue

            details = _place_details_essentials(client, pid, key)
            api_calls["place_details"] += 1
            if not details:
                print("  -> drop building (Place Details failed)\n")
                continue

            building_ll = (details["lat"], details["lon"])

            station_resolved: list[tuple[str, int, dict]] = []
            for st_name, stated_min in stations:
                geo = _geocode_station(client, st_name, key)
                api_calls["geocode"] += 1
                if geo and geo.get("place_id"):
                    station_resolved.append((st_name, stated_min, geo))
                elif geo:
                    print(f"    -> drop station {st_name!r} (no place_id in geocode response)")

            if not station_resolved:
                print("  -> no stations resolved\n")
                continue

            dest_place_ids = [g["place_id"] for _, _, g in station_resolved]
            results = _route_matrix_walk(client, building_ll, dest_place_ids, key)
            api_calls["route_matrix_elements"] += len(dest_place_ids)
            results_by_idx = {r["dest_idx"]: r for r in results}

            print("  per-station summary:")
            for i, (st_name, stated_min, geo) in enumerate(station_resolved):
                r = results_by_idx.get(i)
                stated_str = f"{stated_min}min" if stated_min is not None else "N/A"
                if not r or r.get("condition") != "ROUTE_EXISTS" or not r.get("duration_s"):
                    cond = r.get("condition") if r else "missing"
                    print(f"    {st_name}: stated={stated_str}  actual=N/A (cond={cond})")
                    continue
                actual_min = r["duration_s"] / 60.0
                if stated_min is not None:
                    err_width = actual_min - stated_min
                    err_rate = err_width / stated_min if stated_min else None
                    rate_str = f"{err_rate:+.2%}" if err_rate is not None else "N/A"
                    print(
                        f"    {st_name}: stated={stated_str}  actual={actual_min:.1f}min  "
                        f"width={err_width:+.1f}min  rate={rate_str}  dist={r['distance_m']}m"
                    )
                else:
                    err_width = None
                    err_rate = None
                    print(f"    {st_name}: stated={stated_str}  actual={actual_min:.1f}min  dist={r['distance_m']}m")
                rows.append(
                    {
                        "building_title": title,
                        "building_address": address,
                        "building_lat": building_ll[0],
                        "building_lon": building_ll[1],
                        "station": st_name,
                        "station_lat": geo["lat"],
                        "station_lon": geo["lon"],
                        "stated_min": stated_min if stated_min is not None else "",
                        "actual_min": round(actual_min, 2),
                        "error_width_min": round(err_width, 2) if err_width is not None else "",
                        "error_rate": round(err_rate, 4) if err_rate is not None else "",
                        "distance_m": r["distance_m"],
                    }
                )
            print()

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "building_title",
                "building_address",
                "building_lat",
                "building_lon",
                "station",
                "station_lat",
                "station_lon",
                "stated_min",
                "actual_min",
                "error_width_min",
                "error_rate",
                "distance_m",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows: {OUTPUT_CSV}")

    print("\nAPI call counts (all within free monthly caps):")
    for k, v in api_calls.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
