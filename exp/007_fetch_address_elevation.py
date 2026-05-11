"""Fetch elevation (m) for every unique listing address.

Pipeline:
  1. Collect unique addresses from `data/001_fetch_suumo/listings.jsonl`.
  2. Resolve (lat, lon) via the JIS 大字町丁目 CSVs in `data/input/address_data/`
     — a local table-lookup, no API call.
  3. Fetch elevation via GSI 標高 API → meters, in parallel with retries.

GSI's geocode API was reachable but routinely 5–15s per request, making a
sequential pipeline take hours. The JIS CSVs already carry per-丁目 lat/lon,
so geocoding becomes a dict lookup. Only the elevation API remains as a
remote call, and it's parallelized.

A JSON cache is kept under `cache/` so reruns only fetch missing entries.
"""

import csv
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import click
from curl_cffi import requests

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"
ADDRESS_DIR = DATA_DIR / "input" / "address_data"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
CACHE_DIR = OUTPUT_DIR / "cache"
ELEVATION_CACHE = CACHE_DIR / "elevation.json"
OUTPUT_CSV = OUTPUT_DIR / "address_elevation.csv"

ELEVATION_URL = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"
IMPERSONATE_TARGET = "safari18_0"
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_WORKERS = 8
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
PROGRESS_INTERVAL = 100
CACHE_FLUSH_INTERVAL = 200

ARABIC_TO_KANJI_CHOME = {
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
    "10": "十",
    "11": "十一",
    "12": "十二",
}
WARD_SPLIT_RE = re.compile(r"^([^区市町村]+[区市町村])(.+)$")
TRAILING_NUM_RE = re.compile(r"^(.+?)(\d+)$")


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _save_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load_unique_addresses(path: Path) -> list[str]:
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            a = r.get("address")
            if a:
                seen.add(a)
    return sorted(seen)


def _normalize_for_lookup(s: str) -> str:
    """NFKC + collapse ヶ↔ケ so listing addresses match the JIS CSV form."""
    s = unicodedata.normalize("NFKC", s)
    return s.replace("ヶ", "ケ")


def _build_jis_table(address_dir: Path) -> dict[tuple[str, str], tuple[float, float]]:
    table: dict[tuple[str, str], tuple[float, float]] = {}
    for csv_path in sorted(address_dir.glob("*.csv")):
        with csv_path.open(encoding="cp932", newline="") as f:
            for row in csv.DictReader(f):
                ward = row["市区町村名"].strip()
                area = _normalize_for_lookup(row["大字町丁目名"].strip())
                try:
                    lat = float(row["緯度"])
                    lon = float(row["経度"])
                except (KeyError, ValueError):
                    continue
                table[(ward, area)] = (lat, lon)
    return table


def _address_to_key(address: str) -> tuple[str, str] | None:
    a = _normalize_for_lookup(address)
    if not a.startswith("東京都"):
        return None
    rest = a[len("東京都") :]
    m = WARD_SPLIT_RE.match(rest)
    if not m:
        return None
    ward, area = m.group(1), m.group(2)
    m2 = TRAILING_NUM_RE.match(area)
    if m2:
        stem, num = m2.group(1), m2.group(2)
        kanji = ARABIC_TO_KANJI_CHOME.get(num)
        if kanji is None:
            return None
        area = f"{stem}{kanji}丁目"
    return ward, area


def _resolve_local_coords(
    addresses: list[str], table: dict[tuple[str, str], tuple[float, float]]
) -> tuple[dict[str, tuple[float, float]], list[str]]:
    resolved: dict[str, tuple[float, float]] = {}
    misses: list[str] = []
    for addr in addresses:
        key = _address_to_key(addr)
        coords = table.get(key) if key else None
        if coords is None:
            misses.append(addr)
        else:
            resolved[addr] = coords
    return resolved, misses


def _fetch_elevation_once(session: requests.Session, lat: float, lon: float) -> float | None:
    r = session.get(
        ELEVATION_URL,
        params={"lat": lat, "lon": lon, "outtype": "JSON"},
        impersonate=IMPERSONATE_TARGET,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    payload = r.json()
    elev = payload.get("elevation")
    if elev in (None, "-----"):
        return None
    return float(elev)


def _fetch_elevation_with_retry(lat: float, lon: float) -> tuple[float | None, str | None]:
    """Return (elevation, None) on success or (None, error_str) on final failure."""
    last_error: str | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            session = requests.Session()
            elev = _fetch_elevation_once(session, lat, lon)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        else:
            return elev, None
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    return None, last_error


def _resolve_elevations(resolved_coords: dict[str, tuple[float, float]], cache: dict) -> dict:
    pending = [a for a in resolved_coords if "elevation_m" not in cache.get(a, {})]
    if not pending:
        print(f"elevation: all {len(resolved_coords):,} addresses already cached")
        return cache
    cached_ok = sum(1 for v in cache.values() if "elevation_m" in v)
    print(f"elevation: fetching {len(pending):,} (cached {cached_ok:,}, workers={MAX_WORKERS})")

    lock = Lock()
    done = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_addr = {executor.submit(_fetch_elevation_with_retry, *resolved_coords[a]): a for a in pending}
        for fut in as_completed(future_to_addr):
            addr = future_to_addr[fut]
            elev, err = fut.result()
            with lock:
                if err is not None:
                    errors += 1
                elif elev is None:
                    cache[addr] = {"error": "no elevation"}
                else:
                    cache[addr] = {"elevation_m": elev}
                done += 1
                if done % PROGRESS_INTERVAL == 0 or done == len(pending):
                    print(f"  elevation {done:,}/{len(pending):,} (errors so far: {errors:,})")
                if done % CACHE_FLUSH_INTERVAL == 0:
                    _save_cache(ELEVATION_CACHE, cache)
    _save_cache(ELEVATION_CACHE, cache)
    return cache


def _write_csv(
    addresses: list[str],
    coords: dict[str, tuple[float, float]],
    elevation: dict,
    path: Path,
) -> None:
    rows = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["address", "lat", "lon", "elevation_m"])
        for addr in addresses:
            ll = coords.get(addr)
            e = elevation.get(addr, {})
            lat = ll[0] if ll else ""
            lon = ll[1] if ll else ""
            elev = e.get("elevation_m", "")
            w.writerow([addr, lat, lon, elev])
            rows += 1
    print(f"wrote {rows:,} rows: {path}")


@click.command()
@click.option("--limit", type=int, default=None, help="Process only the first N addresses (for testing).")
def main(limit: int | None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    addresses = _load_unique_addresses(LISTINGS_PATH)
    if limit is not None:
        addresses = addresses[:limit]
    print(f"unique addresses: {len(addresses):,}")

    print("building local JIS lat/lon table...")
    table = _build_jis_table(ADDRESS_DIR)
    print(f"  {len(table):,} (ward, area) entries")

    coords, misses = _resolve_local_coords(addresses, table)
    print(f"local geocode: hit {len(coords):,}, miss {len(misses):,}")
    if misses[:5]:
        print("  miss samples:")
        for a in misses[:5]:
            print(f"    {a}")

    elevation = _resolve_elevations(coords, _load_cache(ELEVATION_CACHE))

    resolved = sum(1 for a in addresses if "elevation_m" in elevation.get(a, {}))
    elev_errors = sum(1 for a in addresses if a in coords and "error" in elevation.get(a, {}))
    elev_missing = sum(1 for a in addresses if a in coords and a not in elevation)
    print(f"\nresolved elevations: {resolved:,}/{len(addresses):,}")
    print(f"  geocode misses: {len(misses):,}")
    print(f"  elevation errors (cached): {elev_errors:,}")
    print(f"  elevation pending (transient failures, retry on rerun): {elev_missing:,}")

    _write_csv(addresses, coords, elevation, OUTPUT_CSV)


if __name__ == "__main__":
    main()
