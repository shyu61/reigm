"""Fetch Tokyo 23-ku railway station names from MLIT 国土数値情報 (N02).

Downloads the N02 (railway) GML/GeoJSON archive from MLIT, filters station
features whose representative point falls within the 23-ku bounding box, and
writes deduped station names to `data/004_fetch_station_data/tokyo_23ku_stations.txt`
(one per line). The output is consumed by 003_analyze_property_name_words.py.
"""

import io
import json
import zipfile
from pathlib import Path

from curl_cffi import requests

N02_ZIP_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-22/N02-22_GML.zip"
GEOJSON_MEMBER = "UTF-8/N02-22_Station.geojson"
IMPERSONATE_TARGET = "safari18_0"
REQUEST_TIMEOUT_SECONDS = 60.0

# Tokyo 23-ku approximate bounding box.
LAT_MIN, LAT_MAX = 35.50, 35.82
LNG_MIN, LNG_MAX = 139.55, 139.95

SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent.parent / "data" / SCRIPT_PATH.stem
OUTPUT_PATH = OUTPUT_DIR / "tokyo_23ku_stations.txt"


def fetch_zip(url: str) -> bytes:
    print(f"downloading: {url}")
    r = requests.get(url, impersonate=IMPERSONATE_TARGET, timeout=REQUEST_TIMEOUT_SECONDS)
    r.raise_for_status()
    print(f"downloaded: {len(r.content):,} bytes")
    return r.content


def load_station_geojson(zip_bytes: bytes, member: str) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with zf.open(member) as f:
            return json.load(f)


def extract_23ku_station_names(geojson: dict) -> set[str]:
    names: set[str] = set()
    for feat in geojson["features"]:
        coords = feat["geometry"]["coordinates"]
        if not coords:
            continue
        lng, lat = coords[0][0], coords[0][1]
        if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
            continue
        n = feat["properties"].get("N02_005", "").strip()
        if n:
            names.add(n)
    return names


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    zip_bytes = fetch_zip(N02_ZIP_URL)
    geojson = load_station_geojson(zip_bytes, GEOJSON_MEMBER)
    print(f"total station features: {len(geojson['features']):,}")

    names = extract_23ku_station_names(geojson)
    print(f"unique stations in 23-ku bbox: {len(names):,}")

    OUTPUT_PATH.write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")
    print(f"wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
