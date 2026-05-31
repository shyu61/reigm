"""Re-geocode the 3 mis-located stations via Places Text Search and patch the cache.

exp/018 geocoded stations with the Geocoding API, which is address-centric and
fuzzy-matches POI/landmark names. Three stations resolved to the wrong place
(verified in the analysis):
  東高円寺駅   → JR 高円寺駅 (~630m off; "東" dropped, matched train_station)
  緑が丘駅     → 緑が丘駅 in 兵庫県三木市 (~540km; same name, wrong prefecture)
  南阿佐ケ谷駅 → degenerate "日本" centroid in Nagano/Gunma (~179km)

Places Text Search resolves establishments/transit POIs correctly (the same path
the buildings used). This re-queries each station with a Tokyo location bias, picks
the best transit-station candidate inside the Tokyo bbox, and overwrites that
station's record in data/018.../cache/station_geocode.jsonl (a .bak is written
first). A corrected-stations record + raw responses are saved here for audit.

This ONLY fixes the geocode. Routes are NOT recomputed — the next exp/018 run will
see the new station place_ids miss the route cache and re-route just those pairs.

--dry-run resolves and prints the before/after without touching the cache.
Required: GOOGLE_MAPS_API_KEY with Places API (New) enabled.
"""

import json
import shutil
from pathlib import Path

import click
import httpx

from settings import settings

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
STATION_CACHE = DATA_DIR / "018_fetch_walk_times" / "cache" / "station_geocode.jsonl"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
CORRECTED_CSV = OUTPUT_DIR / "corrected_stations.jsonl"
RAW_LOG = OUTPUT_DIR / "raw_responses.jsonl"

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
REQUEST_TIMEOUT = 30.0

STATIONS_TO_FIX = ["東高円寺駅", "緑が丘駅", "南阿佐ケ谷駅"]
# Tokyo 23-ku bbox (SW, NE) — same window used to bias exp/018's geocoding.
TOKYO_SW = (35.50, 139.55)
TOKYO_NE = (35.85, 139.95)
TRANSIT_TYPES = {"subway_station", "train_station", "transit_station", "light_rail_station"}


def _places_search(client: httpx.Client, query: str, key: str) -> list[dict]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress,places.types",
    }
    body = {
        "textQuery": query,
        "languageCode": "ja",
        "regionCode": "JP",
        "maxResultCount": 5,
        "locationBias": {
            "rectangle": {
                "low": {"latitude": TOKYO_SW[0], "longitude": TOKYO_SW[1]},
                "high": {"latitude": TOKYO_NE[0], "longitude": TOKYO_NE[1]},
            }
        },
    }
    r = client.post(PLACES_TEXT_SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    if not r.is_success:
        print(f"    !! HTTP {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    data = r.json()
    with RAW_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"query": query, "response": data}, ensure_ascii=False) + "\n")
    return data.get("places") or []


def _in_tokyo(loc: dict) -> bool:
    lat, lng = loc.get("latitude"), loc.get("longitude")
    return lat is not None and TOKYO_SW[0] <= lat <= TOKYO_NE[0] and TOKYO_SW[1] <= lng <= TOKYO_NE[1]


def _pick_best(candidates: list[dict], station: str) -> dict | None:
    """Score candidates: must be in Tokyo; prefer transit type and exact name match."""
    best, best_score = None, -1
    for c in candidates:
        loc = c.get("location") or {}
        if not _in_tokyo(loc):
            continue
        name = (c.get("displayName") or {}).get("text", "")
        types = set(c.get("types") or [])
        score = 0
        if types & TRANSIT_TYPES:
            score += 4
        if name == station:
            score += 3
        elif station.rstrip("駅") in name:
            score += 1
        if score > best_score:
            best, best_score = c, score
    return best


@click.command()
@click.option("--dry-run", is_flag=True, help="Resolve and print before/after without patching the cache.")
def main(dry_run: bool) -> None:
    key = settings.google_maps_api_key
    if not key:
        raise click.ClickException("GOOGLE_MAPS_API_KEY is not set in .env.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Load current cache (last-wins, preserve order) so we know the old values.
    records: dict[str, dict] = {}
    for line in STATION_CACHE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            records[rec["station"]] = rec

    corrected: dict[str, dict] = {}
    with httpx.Client() as client:
        for station in STATIONS_TO_FIX:
            old = records.get(station, {})
            best = _pick_best(_places_search(client, station, key), station)
            if not best:
                print(f"  !! {station}: no in-Tokyo transit candidate found — leaving unchanged")
                continue
            loc = best["location"]
            new = {
                "station": station,
                "lat": loc["latitude"],
                "lon": loc["longitude"],
                "place_id": best["id"],
                "formatted_address": best.get("formattedAddress"),
            }
            corrected[station] = new
            name = (best.get("displayName") or {}).get("text", "")
            print(f"  {station}:")
            print(f"    old: {old.get('lat')},{old.get('lon')}  {old.get('formatted_address')}")
            print(f"    new: {new['lat']},{new['lon']}  [{name}] {new['formatted_address']}")
            print(f"         types={best.get('types')}")

    if not corrected:
        print("\nnothing corrected.")
        return

    with CORRECTED_CSV.open("w", encoding="utf-8") as f:
        for rec in corrected.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nwrote corrected records: {CORRECTED_CSV}")

    if dry_run:
        print("[dry-run] cache NOT patched.")
        return

    # Patch: back up, apply corrections (last-wins), rewrite preserving order.
    shutil.copy2(STATION_CACHE, STATION_CACHE.with_suffix(".jsonl.bak"))
    records.update(corrected)
    with STATION_CACHE.open("w", encoding="utf-8") as f:
        for rec in records.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"patched {len(corrected)} station(s) in {STATION_CACHE} (backup: .jsonl.bak)")
    print("Next: re-run exp/018 to re-route the affected pairs (cached → only these re-bill).")


if __name__ == "__main__":
    main()
