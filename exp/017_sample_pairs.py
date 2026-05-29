"""Sample ~10k (building, station) pairs for the SUUMO-vs-Google walk-time study.

Design (station-stratified, equal allocation, within-station stated_min balanced):

  1. Selection rule: keep stations that have >= STATION_PAIR_THRESHOLD walk-only
     (<=20min, no バス) pairs in SUUMO. A clean, explainable cutoff that drops
     noisy long-tail stations. With threshold=100 this is ~354 stations.
  2. Equal allocation: give every selected station the same target of
     PAIRS_PER_STATION pairs, so per-station means have comparable precision —
     right for a ranking (Topic 1b) and for area-feature analysis (Topic 2),
     where each station is one equal-weight data point.
  3. Within-station balancing: spread each station's quota across the stated_min
     values it offers (round-robin over buckets). Guarantees every表記時間 gets
     samples (Topic 3) and stops a station's particular walk-time mix from
     biasing its mean.

The overall 23-ku average (Topic 1a) is NOT the raw mean of this sample (equal
allocation over-weights small stations). Recover an unbiased figure downstream
with station_total_pairs as the weight:
    weighted_mean = Σ(station_total_pairs * station_sample_mean) / Σ(station_total_pairs)
station_total_pairs is emitted per row so this is exact.

No API calls — pure local sampling from `data/001_fetch_suumo/listings.jsonl`.
Deterministic given SEED. Use --max-stations for a tiny-scale smoke check.
"""

import csv
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import click

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
OUTPUT_CSV = OUTPUT_DIR / "sampled_pairs.csv"
OUTPUT_STATS = OUTPUT_DIR / "sample_stats.json"

# Same descriptive-title filter as exp/016: titles that are listing blurbs, not
# building names, have nothing for Places Text Search to resolve.
DESCRIPTIVE_TITLE_RE = re.compile(
    r"駅\s.*階建|築\d+年|戸建|貸家|借家|賃貸|貸マンション|共同住宅|倉庫|店舗|事務所"
    r"|徒歩\d+分|敷礼|角部屋|防犯カメラ|オートロック|宅配ボックス|エレベーター|ペット(?:可|相談)|駐車場"
)
WALK_RE = re.compile(r"歩(\d+)分")
WARD_RE = re.compile(r"東京都([^区市町村]+[区市町村])")

WALK_CUTOFF_MIN = 20
MIN_STATIONS_PER_BUILDING = 2
STATION_PAIR_THRESHOLD = 100  # keep stations with >= this many SUUMO pairs
PAIRS_PER_STATION = 28  # equal allocation; 354 stations x 28 ≈ 9,912 (<10k free tier)
SEED = 42


def _is_descriptive_title(raw: str) -> bool:
    return bool(DESCRIPTIVE_TITLE_RE.search(unicodedata.normalize("NFKC", raw)))


def _parse_station(entry: str) -> str | None:
    if "/" not in entry:
        return None
    return entry.split("/", 1)[1].split(" ", 1)[0]


def _parse_ward(address: str) -> str:
    m = WARD_RE.match(address)
    return m.group(1) if m else "?"


def _load_buildings(path: Path) -> dict[tuple[str, str], dict]:
    """Dedup to unique (title, address) buildings, each with {station: min stated_min}.

    Walk-only access, <=20min, no バス. Buildings with <2 distinct stations dropped.
    """
    buildings: dict[tuple[str, str], dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            title, address = r.get("title"), r.get("address")
            if not title or not address or _is_descriptive_title(title):
                continue
            stations: dict[str, int] = {}
            for entry in r.get("access") or []:
                if "バス" in entry:
                    continue
                station = _parse_station(entry)
                match = WALK_RE.search(entry)
                if not station or not match:
                    continue
                mins = int(match.group(1))
                if mins > WALK_CUTOFF_MIN:
                    continue
                # Keep the shortest stated time if the same station repeats.
                if station not in stations or mins < stations[station]:
                    stations[station] = mins
            if len(stations) < MIN_STATIONS_PER_BUILDING:
                continue
            key = (title, address)
            if key not in buildings:
                buildings[key] = {"ward": _parse_ward(address), "stations": stations}
    return buildings


def _allocate_station(pairs: list[tuple], target: int, rng: random.Random) -> list[tuple]:
    """Pick `target` pairs for one station, balanced across stated_min buckets.

    Round-robins over stated_min buckets (sorted) so the quota spreads across表記
    時間. Within a bucket, picks purely at random (seeded shuffle) — we do NOT bias
    selection toward buildings shared with other stations: that would over-sample
    inter-station overlap zones and risk an upward bias on per-station error, and
    it saves nothing (Place Details stays inside the free tier either way).
    Same-building cross-station contrasts still arise naturally for Topic 3.
    """
    buckets: dict[int, list[tuple]] = defaultdict(list)
    for p in pairs:
        buckets[p[2]].append(p)  # p = (building_key, station, stated_min)
    for m in buckets:
        rng.shuffle(buckets[m])

    bucket_keys = sorted(buckets.keys())
    chosen: list[tuple] = []
    while len(chosen) < target:
        progressed = False
        for m in bucket_keys:
            if len(chosen) >= target:
                break
            bucket = buckets[m]
            if not bucket:
                continue
            chosen.append(bucket.pop())  # bucket is shuffled → pop() is a random draw
            progressed = True
        if not progressed:
            break
    return chosen


@click.command()
@click.option(
    "--max-stations",
    type=int,
    default=None,
    help="Cap the number of stations sampled (for tiny-scale verification). Default: all eligible.",
)
def main(max_stations: int | None) -> None:
    rng = random.Random(SEED)

    buildings = _load_buildings(LISTINGS_PATH)
    print(f"loaded {len(buildings):,} unique buildings (>= {MIN_STATIONS_PER_BUILDING} stations)")

    # All pairs + per-station population counts.
    pairs_by_station: dict[str, list[tuple]] = defaultdict(list)
    for key, b in buildings.items():
        for station, stated_min in b["stations"].items():
            pairs_by_station[station].append((key, station, stated_min))
    station_total_pairs = {st: len(ps) for st, ps in pairs_by_station.items()}

    eligible = sorted(
        (st for st, n in station_total_pairs.items() if n >= STATION_PAIR_THRESHOLD),
        key=lambda st: (-station_total_pairs[st], st),
    )
    print(f"eligible stations (>= {STATION_PAIR_THRESHOLD} pairs): {len(eligible):,}")
    if max_stations is not None:
        eligible = eligible[:max_stations]
        print(f"  capped to {len(eligible)} stations for this run")

    sampled: list[dict] = []
    per_station_count: dict[str, int] = {}
    for station in eligible:
        chosen = _allocate_station(pairs_by_station[station], PAIRS_PER_STATION, rng)
        per_station_count[station] = len(chosen)
        for (title, address), st, stated_min in chosen:
            sampled.append(
                {
                    "building_title": title,
                    "building_address": address,
                    "ward": buildings[(title, address)]["ward"],
                    "station": st,
                    "stated_min": stated_min,
                    "station_total_pairs": station_total_pairs[st],
                }
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["building_title", "building_address", "ward", "station", "stated_min", "station_total_pairs"],
        )
        w.writeheader()
        w.writerows(sampled)

    # Summary / reproducibility stats.
    stated_hist = Counter(row["stated_min"] for row in sampled)
    ward_hist = Counter(row["ward"] for row in sampled)
    counts = list(per_station_count.values())
    distinct_buildings = len({(r["building_title"], r["building_address"]) for r in sampled})
    stats = {
        "seed": SEED,
        "threshold": STATION_PAIR_THRESHOLD,
        "pairs_per_station": PAIRS_PER_STATION,
        "stations_selected": len(eligible),
        "total_pairs": len(sampled),
        "distinct_buildings": distinct_buildings,
        "building_reuse_ratio": round(len(sampled) / distinct_buildings, 3) if distinct_buildings else 0,
        "per_station_min": min(counts) if counts else 0,
        "per_station_max": max(counts) if counts else 0,
        "stated_min_hist": {str(k): stated_hist[k] for k in sorted(stated_hist)},
        "ward_hist": dict(sorted(ward_hist.items(), key=lambda kv: -kv[1])),
    }
    with OUTPUT_STATS.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\nwrote {len(sampled):,} pairs: {OUTPUT_CSV}")
    print(f"  stations: {len(eligible):,}  distinct buildings: {distinct_buildings:,}")
    print(f"  per-station count: min={stats['per_station_min']} max={stats['per_station_max']}")
    print(f"  building reuse ratio: {stats['building_reuse_ratio']}")
    print("  stated_min spread:")
    for m in sorted(stated_hist):
        print(f"    {m:2d}分: {stated_hist[m]:,}")
    print(f"  wards covered: {len(ward_hist)}")
    print(f"\nwrote stats: {OUTPUT_STATS}")
    if len(sampled) > 10_000:
        print(f"\n!! WARNING: {len(sampled):,} pairs exceeds the 10k Route Matrix free tier.")


if __name__ == "__main__":
    main()
