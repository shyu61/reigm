"""Fetch Google Maps walking times for the sampled pairs from exp/017.

Reads `data/017_sample_pairs/sampled_pairs.csv` and resolves, per pair:
  1. Building → lat/lon via Places Text Search (IDs only, free) + Place Details
     (Essentials). Keyed/cached by (title, address).
  2. Station → place_id + lat/lon via Geocoding API. Cached per station name.
  3. Walking duration via Routes API computeRouteMatrix: building origin as
     latLng, station destinations as placeId (so the route targets a station
     access point, not a road-snapped centroid — see exp/016 findings).

Cost safety / robustness:
  * Every API result is written to an append-only JSONL cache under
    `cache/`. Re-runs skip cached work, so a crash never re-bills and resuming
    is free. The route cache is keyed by (building_place_id, station_place_id).
  * Every raw API response is also appended verbatim to `cache/raw_responses.jsonl`
    (tagged by api + ref) so fields can be re-extracted or audited without
    re-calling.
  * One Route Matrix call per building (origin × its sampled stations). Batching
    across buildings would compute unwanted origin×destination cross-products
    and waste billable elements, so we don't.
  * --dry-run prints the exact number of *new* (billable) calls without making
    any. --limit N processes only the first N buildings (tiny-scale check).
  * Concurrent: stations are geocoded first (phase 1, deduped), then buildings
    are processed in a thread pool (phase 2). --workers sets the pool size.
    Cache writes are serialized by a lock; HTTP runs in parallel.

Required: GOOGLE_MAPS_API_KEY in `.env` with Places API (New), Geocoding API,
Routes API enabled. Full set ≈ 9.9k elements + ≈9.9k Place Details — inside the
10k/month free tier for each SKU.
"""

import csv
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
import httpx

from settings import settings

# Guards all append-only cache/raw writes so worker threads don't interleave lines.
_WRITE_LOCK = threading.Lock()
DEFAULT_WORKERS = 8

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
SAMPLED_CSV = DATA_DIR / "017_sample_pairs" / "sampled_pairs.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
OUTPUT_CSV = OUTPUT_DIR / "walk_times.csv"
CACHE_DIR = OUTPUT_DIR / "cache"
BUILDING_CACHE = CACHE_DIR / "building_geocode.jsonl"
STATION_CACHE = CACHE_DIR / "station_geocode.jsonl"
ROUTE_CACHE = CACHE_DIR / "routes.jsonl"
# Append-only audit log of every raw API response (write-only; never read back on
# resume). Lets us re-extract fields or debug surprises without re-calling.
RAW_LOG = CACHE_DIR / "raw_responses.jsonl"

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL_TEMPLATE = "https://places.googleapis.com/v1/places/{place_id}"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTE_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

# Rough bbox covering Tokyo 23-ku, used to bias Geocoding API results.
TOKYO_BOUNDS = "35.50,139.55|35.85,139.95"
REQUEST_TIMEOUT = 30.0
# Once this many buildings have errored, stop dispatching new work — almost always
# a quota or auth problem, not bad data. Cached progress is saved; fix and re-run.
MAX_ERRORS = 25
# Transient HTTP statuses worth retrying: 429 = per-minute quota, 503 = backend blip.
# We back off exponentially with jitter so concurrent workers spread across the next
# quota-minute instead of all retrying in lockstep.
RETRY_STATUSES = {429, 503}
MAX_RETRIES = 6
BACKOFF_BASE = 2.0  # seconds; delay = BACKOFF_BASE * 2**attempt + jitter

OUTPUT_FIELDS = [
    "building_title",
    "building_address",
    "ward",
    "station",
    "stated_min",
    "station_total_pairs",
    "building_lat",
    "building_lon",
    "building_place_id",
    "station_lat",
    "station_lon",
    "station_place_id",
    "actual_min",
    "error_width_min",
    "error_rate",
    "distance_m",
    "condition",
    "status",
]


# --- cache helpers ---------------------------------------------------------


def _load_jsonl(path: Path, key_field: str) -> dict:
    out: dict = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                out[rec[key_field]] = rec
    return out


def _append_jsonl(path: Path, rec: dict) -> None:
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _WRITE_LOCK, path.open("a", encoding="utf-8") as f:
        f.write(line)


def _building_key(title: str, address: str) -> str:
    return f"{title}\t{address}"


def _route_key(building_place_id: str, station_place_id: str) -> str:
    return f"{building_place_id}|{station_place_id}"


# --- API calls (verified in exp/016) ---------------------------------------


def _check(r: httpx.Response, label: str) -> None:
    if r.is_success:
        return
    print(f"    !! {label} HTTP {r.status_code}: {r.text[:400]}")
    r.raise_for_status()


def _send(client: httpx.Client, method: str, url: str, label: str, **kwargs) -> httpx.Response:
    """Perform an HTTP request, retrying transient quota/availability errors with
    exponential backoff + jitter. Honors a numeric Retry-After when present. Raises
    (via _check) on non-retryable errors or once retries are exhausted."""
    r = None
    for attempt in range(MAX_RETRIES + 1):
        r = client.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        if r.is_success or r.status_code not in RETRY_STATUSES or attempt == MAX_RETRIES:
            break
        retry_after = r.headers.get("Retry-After", "")
        if retry_after.isdigit():
            delay = float(retry_after)
        else:
            delay = BACKOFF_BASE * (2**attempt) + random.uniform(0, 1)
        print(f"    .. {label} HTTP {r.status_code}; retry {attempt + 1}/{MAX_RETRIES} in {delay:.1f}s")
        time.sleep(delay)
    _check(r, label)
    return r


def _log_raw(api: str, ref: str, response: object) -> None:
    """Append one raw API response to the audit log, tagged with the API and a ref key."""
    _append_jsonl(RAW_LOG, {"api": api, "ref": ref, "response": response})


def _places_text_search_id(client: httpx.Client, query: str, key: str) -> str | None:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id",
    }
    body = {"textQuery": query, "languageCode": "ja", "regionCode": "JP", "maxResultCount": 1}
    r = _send(client, "POST", PLACES_TEXT_SEARCH_URL, "TextSearch", headers=headers, json=body)
    data = r.json()
    _log_raw("text_search", query, data)
    places = data.get("places") or []
    return places[0].get("id") if places else None


def _place_details_essentials(client: httpx.Client, place_id: str, key: str) -> dict | None:
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": "location,formattedAddress,types"}
    url = PLACE_DETAILS_URL_TEMPLATE.format(place_id=place_id)
    r = _send(client, "GET", url, "PlaceDetails", headers=headers, params={"languageCode": "ja"})
    data = r.json()
    _log_raw("place_details", place_id, data)
    loc = data.get("location")
    if not loc:
        return None
    return {
        "lat": loc["latitude"],
        "lon": loc["longitude"],
        "formatted_address": data.get("formattedAddress"),
        "types": data.get("types") or [],
    }


def _geocode_station(client: httpx.Client, name: str, key: str) -> dict | None:
    params = {
        "address": name,
        "region": "jp",
        "language": "ja",
        "components": "country:JP",
        "bounds": TOKYO_BOUNDS,
        "key": key,
    }
    r = _send(client, "GET", GEOCODE_URL, "Geocode", params=params)
    data = r.json()
    _log_raw("geocode", name, data)
    results = data.get("results") or []
    if data.get("status") != "OK" or not results:
        return None
    g = results[0]
    loc = g["geometry"]["location"]
    return {
        "lat": loc["lat"],
        "lon": loc["lng"],
        "place_id": g.get("place_id"),
        "formatted_address": g.get("formatted_address"),
    }


def _route_matrix_walk(
    client: httpx.Client,
    origin: tuple[float, float],
    destination_place_ids: list[str],
    key: str,
    ref: str,
) -> list[dict]:
    """Walking durations from a building origin (latLng) to station destinations (placeId)."""
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
    r = _send(client, "POST", ROUTE_MATRIX_URL, "RouteMatrix", headers=headers, json=body)
    data = r.json()
    _log_raw("route_matrix", ref, data)
    out: list[dict] = []
    for row in data:
        dur = row.get("duration", "0s")
        try:
            duration_s = float(dur.rstrip("s"))
        except (ValueError, AttributeError):
            duration_s = 0.0
        out.append(
            {
                "dest_idx": row.get("destinationIndex", 0),
                "duration_s": duration_s,
                "distance_m": row.get("distanceMeters"),
                "condition": row.get("condition"),
            }
        )
    return out


# --- input -----------------------------------------------------------------


def _load_sampled(path: Path) -> list[dict]:
    """Group sampled rows by building, preserving CSV order of first appearance."""
    grouped: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bkey = _building_key(row["building_title"], row["building_address"])
            b = grouped.setdefault(
                bkey,
                {
                    "title": row["building_title"],
                    "address": row["building_address"],
                    "ward": row["ward"],
                    "stations": [],
                },
            )
            b["stations"].append(
                {
                    "station": row["station"],
                    "stated_min": int(row["stated_min"]),
                    "station_total_pairs": int(row["station_total_pairs"]),
                }
            )
    return list(grouped.values())


# --- main ------------------------------------------------------------------


def _geocode_one(client, station, key, station_cache) -> int:
    """Geocode one station and cache it. Returns the number of API calls made (0 or 1)."""
    geo = _geocode_station(client, station, key)
    srec = {"station": station, **(geo or {"place_id": None})}
    with _WRITE_LOCK:
        station_cache[station] = srec
    _append_jsonl(STATION_CACHE, srec)
    return 1


def _process_building(client, b, key, building_cache, station_cache, route_cache, abort) -> dict:
    """Resolve one building's geocode + its uncached routes. Returns per-API call counts.

    Station geocodes are assumed already populated (done in a prior phase), so this
    only reads station_cache — no station writes here, which keeps the building phase
    free of cross-building station races. Returns immediately if `abort` is set, so
    queued work drains fast once the API is clearly failing.
    """
    counts = {"text_search": 0, "place_details": 0, "route_matrix_elements": 0}
    if abort.is_set():
        return counts
    title, address = b["title"], b["address"]
    bkey = _building_key(title, address)

    if bkey not in building_cache:
        pid = _places_text_search_id(client, f"{title} {address}", key)
        counts["text_search"] += 1
        rec = {"key": bkey, "place_id": pid}
        if pid:
            details = _place_details_essentials(client, pid, key)
            counts["place_details"] += 1
            if details:
                rec.update(details)
        with _WRITE_LOCK:
            building_cache[bkey] = rec
        _append_jsonl(BUILDING_CACHE, rec)
    brec = building_cache[bkey]

    if not (brec.get("place_id") and brec.get("lat") is not None):
        return counts

    pending: list[tuple] = []  # (station_place_id,)
    for s in b["stations"]:
        srec = station_cache.get(s["station"], {})
        s_pid = srec.get("place_id")
        if s_pid and _route_key(brec["place_id"], s_pid) not in route_cache:
            pending.append(s_pid)
    if pending:
        results = _route_matrix_walk(client, (brec["lat"], brec["lon"]), pending, key, brec["place_id"])
        counts["route_matrix_elements"] += len(pending)
        by_idx = {r["dest_idx"]: r for r in results}
        for idx, s_pid in enumerate(pending):
            r = by_idx.get(idx, {})
            rrec = {
                "key": _route_key(brec["place_id"], s_pid),
                "duration_s": r.get("duration_s"),
                "distance_m": r.get("distance_m"),
                "condition": r.get("condition"),
            }
            with _WRITE_LOCK:
                route_cache[rrec["key"]] = rrec
            _append_jsonl(ROUTE_CACHE, rrec)
    return counts


@click.command()
@click.option("--limit", type=int, default=None, help="Process only the first N buildings (tiny-scale verification).")
@click.option("--dry-run", is_flag=True, help="Report the number of new (billable) calls without making any.")
@click.option("--workers", type=int, default=DEFAULT_WORKERS, show_default=True, help="Concurrent request workers.")
def main(limit: int | None, dry_run: bool, workers: int) -> None:
    key = settings.google_maps_api_key
    if not key and not dry_run:
        raise click.ClickException("GOOGLE_MAPS_API_KEY is not set in .env.")

    buildings = _load_sampled(SAMPLED_CSV)
    if limit is not None:
        buildings = buildings[:limit]
    total_pairs = sum(len(b["stations"]) for b in buildings)
    print(f"loaded {len(buildings):,} buildings / {total_pairs:,} pairs from {SAMPLED_CSV.name}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    building_cache = _load_jsonl(BUILDING_CACHE, "key")
    station_cache = _load_jsonl(STATION_CACHE, "station")
    route_cache = _load_jsonl(ROUTE_CACHE, "key")
    print(f"cache: {len(building_cache):,} buildings, {len(station_cache):,} stations, {len(route_cache):,} routes")

    # Count work still to do (new = billable).
    new_b = sum(1 for b in buildings if _building_key(b["title"], b["address"]) not in building_cache)
    needed_stations = {s["station"] for b in buildings for s in b["stations"]}
    new_s = sorted(st for st in needed_stations if st not in station_cache)
    print(f"to fetch: {new_b:,} new buildings, {len(new_s):,} new stations (routes counted as resolved)")

    if dry_run:
        print("\n[dry-run] billable calls that WOULD be made:")
        print(f"  Place Details : {new_b:,}  (Text Search IDs-only is free)")
        print(f"  Geocoding     : {len(new_s):,}")
        print(f"  Route Matrix  : up to {total_pairs:,} elements (already-cached routes skipped)")
        print("  → all three SKUs have a 10k/month free tier.")
        return

    api_calls = {"text_search": 0, "place_details": 0, "geocode": 0, "route_matrix_elements": 0}

    with httpx.Client() as client:
        # Phase 1: geocode all missing stations first (deduped), so the building
        # phase only reads station_cache and never races on the same station.
        if new_s:
            print(f"\n[phase 1] geocoding {len(new_s):,} stations with {workers} workers...")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_geocode_one, client, st, key, station_cache): st for st in new_s}
                for fut in as_completed(futures):
                    api_calls["geocode"] += fut.result()

        # Phase 2: process buildings concurrently (geocode + routes).
        print(f"\n[phase 2] processing {len(buildings):,} buildings with {workers} workers...")
        abort = threading.Event()
        errors = 0
        done = 0
        start = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_process_building, client, b, key, building_cache, station_cache, route_cache, abort): b
                for b in buildings
            }
            for fut in as_completed(futures):
                b = futures[fut]
                try:
                    counts = fut.result()
                    for k, v in counts.items():
                        api_calls[k] += v
                except httpx.HTTPError as e:
                    errors += 1
                    print(f"  ERROR on {b['title']!r}: {e} (total errors={errors})")
                    if errors >= MAX_ERRORS and not abort.is_set():
                        abort.set()
                        print(f"  too many errors ({errors}); draining queue. Progress is cached — fix and re-run.")
                done += 1
                if done % 250 == 0 or done == len(buildings):
                    rate = done / max(time.time() - start, 1e-6)
                    eta = (len(buildings) - done) / rate if rate else 0
                    print(f"  [{done:,}/{len(buildings):,}] {rate:.1f} bldg/s  ETA {eta / 60:.1f}min  errors={errors}")

    # Assemble output rows from the now-populated caches.
    rows: list[dict] = []
    for b in buildings:
        rows.extend(_build_rows(b, b["title"], b["address"], b["ward"], building_cache, station_cache, route_cache))

    _write_output(rows)
    print(f"\nwrote {len(rows):,} rows: {OUTPUT_CSV}")
    print("API calls this run:")
    for k, v in api_calls.items():
        print(f"  {k}: {v:,}")
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"resolved (status=ok): {ok:,}/{len(rows):,}")


def _build_rows(b, title, address, ward, building_cache, station_cache, route_cache) -> list[dict]:
    bkey = _building_key(title, address)
    brec = building_cache.get(bkey, {})
    out: list[dict] = []
    for s in b["stations"]:
        base = {
            "building_title": title,
            "building_address": address,
            "ward": ward,
            "station": s["station"],
            "stated_min": s["stated_min"],
            "station_total_pairs": s["station_total_pairs"],
            "building_lat": brec.get("lat", ""),
            "building_lon": brec.get("lon", ""),
            "building_place_id": brec.get("place_id", ""),
            "station_lat": "",
            "station_lon": "",
            "station_place_id": "",
            "actual_min": "",
            "error_width_min": "",
            "error_rate": "",
            "distance_m": "",
            "condition": "",
            "status": "",
        }
        if not brec.get("place_id") or brec.get("lat") is None:
            base["status"] = "building_unresolved"
            out.append(base)
            continue
        srec = station_cache.get(s["station"], {})
        base["station_lat"] = srec.get("lat", "")
        base["station_lon"] = srec.get("lon", "")
        base["station_place_id"] = srec.get("place_id", "") or ""
        if not srec.get("place_id"):
            base["status"] = "station_unresolved"
            out.append(base)
            continue
        rrec = route_cache.get(_route_key(brec["place_id"], srec["place_id"]), {})
        cond = rrec.get("condition")
        base["condition"] = cond or ""
        base["distance_m"] = rrec.get("distance_m", "") if rrec.get("distance_m") is not None else ""
        if cond != "ROUTE_EXISTS" or not rrec.get("duration_s"):
            base["status"] = "no_route"
            out.append(base)
            continue
        actual_min = rrec["duration_s"] / 60.0
        width = actual_min - s["stated_min"]
        rate = width / s["stated_min"] if s["stated_min"] else None
        base["actual_min"] = round(actual_min, 2)
        base["error_width_min"] = round(width, 2)
        base["error_rate"] = round(rate, 4) if rate is not None else ""
        base["status"] = "ok"
        out.append(base)
    return out


def _write_output(rows: list[dict]) -> None:
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
