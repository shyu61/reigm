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

Required: GOOGLE_MAPS_API_KEY in `.env` with Places API (New), Geocoding API,
Routes API enabled. Full set ≈ 9.9k elements + ≈9.9k Place Details — inside the
10k/month free tier for each SKU.
"""

import csv
import json
from pathlib import Path

import click
import httpx

from settings import settings

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
# Stop the run if this many buildings error in a row — almost always a quota or
# auth problem, not bad data; better to halt than burn through the list failing.
MAX_CONSECUTIVE_ERRORS = 10

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
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


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
    r = client.post(PLACES_TEXT_SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    _check(r, "TextSearch")
    data = r.json()
    _log_raw("text_search", query, data)
    places = data.get("places") or []
    return places[0].get("id") if places else None


def _place_details_essentials(client: httpx.Client, place_id: str, key: str) -> dict | None:
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": "location,formattedAddress,types"}
    url = PLACE_DETAILS_URL_TEMPLATE.format(place_id=place_id)
    r = client.get(url, headers=headers, params={"languageCode": "ja"}, timeout=REQUEST_TIMEOUT)
    _check(r, "PlaceDetails")
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
    r = client.get(GEOCODE_URL, params=params, timeout=REQUEST_TIMEOUT)
    _check(r, "Geocode")
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
    r = client.post(ROUTE_MATRIX_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    _check(r, "RouteMatrix")
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


@click.command()
@click.option("--limit", type=int, default=None, help="Process only the first N buildings (tiny-scale verification).")
@click.option("--dry-run", is_flag=True, help="Report the number of new (billable) calls without making any.")
def main(limit: int | None, dry_run: bool) -> None:
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
    new_s = sum(1 for st in needed_stations if st not in station_cache)
    print(f"to fetch: {new_b:,} new buildings, {new_s:,} new stations (routes counted as resolved)")

    if dry_run:
        print("\n[dry-run] billable calls that WOULD be made:")
        print(f"  Place Details : {new_b:,}  (Text Search IDs-only is free)")
        print(f"  Geocoding     : {new_s:,}")
        print(f"  Route Matrix  : up to {total_pairs:,} elements (already-cached routes skipped)")
        print("  → all three SKUs have a 10k/month free tier.")
        return

    rows: list[dict] = []
    api_calls = {"text_search": 0, "place_details": 0, "geocode": 0, "route_matrix_elements": 0}
    consecutive_errors = 0

    with httpx.Client() as client:
        for i, b in enumerate(buildings, 1):
            title, address, ward = b["title"], b["address"], b["ward"]
            bkey = _building_key(title, address)
            try:
                # 1. building geocode (cached)
                if bkey not in building_cache:
                    pid = _places_text_search_id(client, f"{title} {address}", key)
                    api_calls["text_search"] += 1
                    rec = {"key": bkey, "place_id": pid}
                    if pid:
                        details = _place_details_essentials(client, pid, key)
                        api_calls["place_details"] += 1
                        if details:
                            rec.update(details)
                    building_cache[bkey] = rec
                    _append_jsonl(BUILDING_CACHE, rec)
                brec = building_cache[bkey]

                # 2. station geocodes (cached, shared across buildings)
                for s in b["stations"]:
                    st = s["station"]
                    if st not in station_cache:
                        geo = _geocode_station(client, st, key)
                        api_calls["geocode"] += 1
                        srec = {"station": st, **(geo or {"place_id": None})}
                        station_cache[st] = srec
                        _append_jsonl(STATION_CACHE, srec)

                # 3. routes — one matrix call per building for uncached, resolvable pairs
                b_resolved = bool(brec.get("place_id") and brec.get("lat") is not None)
                pending: list[tuple] = []  # (station_dict, station_place_id)
                if b_resolved:
                    for s in b["stations"]:
                        srec = station_cache[s["station"]]
                        s_pid = srec.get("place_id")
                        if not s_pid:
                            continue
                        rkey = _route_key(brec["place_id"], s_pid)
                        if rkey not in route_cache:
                            pending.append((s, s_pid))
                    if pending:
                        results = _route_matrix_walk(
                            client, (brec["lat"], brec["lon"]), [p[1] for p in pending], key, brec["place_id"]
                        )
                        api_calls["route_matrix_elements"] += len(pending)
                        by_idx = {r["dest_idx"]: r for r in results}
                        for idx in range(len(pending)):
                            s_pid = pending[idx][1]
                            r = by_idx.get(idx, {})
                            rrec = {
                                "key": _route_key(brec["place_id"], s_pid),
                                "duration_s": r.get("duration_s"),
                                "distance_m": r.get("distance_m"),
                                "condition": r.get("condition"),
                            }
                            route_cache[rrec["key"]] = rrec
                            _append_jsonl(ROUTE_CACHE, rrec)

                consecutive_errors = 0
            except httpx.HTTPError as e:
                consecutive_errors += 1
                print(f"  [{i}/{len(buildings)}] ERROR on {title!r}: {e} (consecutive={consecutive_errors})")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"  aborting after {MAX_CONSECUTIVE_ERRORS} consecutive errors (likely quota/auth).")
                    break
                continue

            # 4. assemble output rows for this building
            rows.extend(_build_rows(b, title, address, ward, building_cache, station_cache, route_cache))
            if i % 250 == 0:
                print(f"  [{i}/{len(buildings)}] processed")

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
