"""Top up the sample for buildings exp/018 could not resolve on Google Places.

exp/018 left some pairs as status=building_unresolved: their (title, address) had
no Places Text Search match — private-residence / generic names (篠原邸, 小野寺方,
玉舎ビル, …) combined with chome-only addresses. That is not fixable by retrying,
and geocoding the bare chome would inject a 200–400m centroid error into the very
walking time we measure. So instead we replace them.

To keep exp/017's station-stratified, stated_min-balanced allocation intact, this
draws replacement pairs from the SAME (station, stated_min) buckets as the
failures, excluding buildings already sampled for that station and the buildings
known to be unresolvable. Replacements are appended to exp/017's sampled_pairs.csv
(the canonical sample file) and recorded in this script's own data dir.

Population definition (descriptive-title filter, walk <= 20min, no バス, >= 2
stations) is copied verbatim from exp/017 so the candidate pool matches the
original sample exactly.

Idempotent: the deficit is recomputed from exp/018's current walk_times.csv and
candidates exclude everything already in the sample, so re-running only fills the
remaining gap. Workflow: run this → re-run exp/018 (cached, so only the new pairs
bill) → optionally repeat until the gap closes.

No new API calls here — pure local resampling. --dry-run reports the deficit and
how many replacements it can fill without writing anything.
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
SAMPLED_CSV = DATA_DIR / "017_sample_pairs" / "sampled_pairs.csv"
WALK_TIMES_CSV = DATA_DIR / "018_fetch_walk_times" / "walk_times.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
REPLACEMENTS_CSV = OUTPUT_DIR / "replacement_pairs.csv"

# --- population definition (verbatim from exp/017, must match the original sample) ---
DESCRIPTIVE_TITLE_RE = re.compile(
    r"駅\s.*階建|築\d+年|戸建|貸家|借家|賃貸|貸マンション|共同住宅|倉庫|店舗|事務所"
    r"|徒歩\d+分|敷礼|角部屋|防犯カメラ|オートロック|宅配ボックス|エレベーター|ペット(?:可|相談)|駐車場"
)
WALK_RE = re.compile(r"歩(\d+)分")
WARD_RE = re.compile(r"東京都([^区市町村]+[区市町村])")

WALK_CUTOFF_MIN = 20
MIN_STATIONS_PER_BUILDING = 2

# Distinct seed from exp/017 (42); exclusion of already-sampled buildings prevents
# overlap regardless, but a different stream keeps draws clearly independent.
SEED = 43

SAMPLED_FIELDS = ["building_title", "building_address", "ward", "station", "stated_min", "station_total_pairs"]


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
                if station not in stations or mins < stations[station]:
                    stations[station] = mins
            if len(stations) < MIN_STATIONS_PER_BUILDING:
                continue
            key = (title, address)
            if key not in buildings:
                buildings[key] = {"ward": _parse_ward(address), "stations": stations}
    return buildings


# --- resampling ------------------------------------------------------------


def _read_sampled(path: Path) -> tuple[list[dict], dict[str, set]]:
    """Return all existing sampled rows and, per station, the set of (title, address)
    already drawn for it — so replacements never duplicate an existing pair."""
    rows: list[dict] = []
    by_station: dict[str, set] = defaultdict(set)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            by_station[row["station"]].add((row["building_title"], row["building_address"]))
    return rows, by_station


def _read_deficits(path: Path) -> tuple[Counter, set]:
    """From exp/018's output, return the per-(station, stated_min) deficit (count of
    building_unresolved pairs) and the set of (title, address) known unresolvable."""
    deficits: Counter = Counter()
    unresolvable: set = set()
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["status"] == "building_unresolved":
                deficits[(row["station"], int(row["stated_min"]))] += 1
                unresolvable.add((row["building_title"], row["building_address"]))
    return deficits, unresolvable


@click.command()
@click.option("--dry-run", is_flag=True, help="Report the deficit and fillable replacements without writing.")
def main(dry_run: bool) -> None:
    buildings = _load_buildings(LISTINGS_PATH)
    pairs_by_station: dict[str, list[tuple]] = defaultdict(list)
    for key, b in buildings.items():
        for station, stated_min in b["stations"].items():
            pairs_by_station[station].append((key, station, stated_min))
    station_total_pairs = {st: len(ps) for st, ps in pairs_by_station.items()}
    print(f"loaded {len(buildings):,} unique buildings")

    _, sampled_by_station = _read_sampled(SAMPLED_CSV)
    deficits, unresolvable = _read_deficits(WALK_TIMES_CSV)
    total_deficit = sum(deficits.values())
    print(f"deficit: {total_deficit:,} pairs across {len(deficits):,} (station, stated_min) cells")
    print(f"known-unresolvable buildings to exclude: {len(unresolvable):,}")

    rng = random.Random(SEED)
    replacements: list[dict] = []
    unfilled: Counter = Counter()
    for (station, stated_min), deficit in sorted(deficits.items()):
        already = sampled_by_station.get(station, set())
        candidates = [
            key
            for key, st, m in pairs_by_station.get(station, [])
            if m == stated_min and key not in already and key not in unresolvable
        ]
        rng.shuffle(candidates)
        take = candidates[:deficit]
        if len(take) < deficit:
            unfilled[(station, stated_min)] = deficit - len(take)
        for title, address in take:
            # Reserve within this run so the same building isn't picked again for
            # this station via another deficit cell.
            already.add((title, address))
            sampled_by_station.setdefault(station, already)
            replacements.append(
                {
                    "building_title": title,
                    "building_address": address,
                    "ward": buildings[(title, address)]["ward"],
                    "station": station,
                    "stated_min": stated_min,
                    "station_total_pairs": station_total_pairs[station],
                }
            )

    print(f"\nreplacements drawn: {len(replacements):,} / {total_deficit:,} deficit")
    if unfilled:
        short = sum(unfilled.values())
        print(f"  !! {short:,} could not be filled (bucket exhausted) in {len(unfilled)} cells:")
        for (st, m), n in sorted(unfilled.items(), key=lambda kv: -kv[1])[:10]:
            print(f"     {st} {m}分: short {n}")

    if dry_run:
        print("\n[dry-run] nothing written.")
        return

    if not replacements:
        print("\nnothing to add.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with REPLACEMENTS_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLED_FIELDS)
        w.writeheader()
        w.writerows(replacements)
    print(f"\nwrote {len(replacements):,} replacement rows: {REPLACEMENTS_CSV}")

    # Append to exp/017's canonical sample so exp/018 picks them up on its next run.
    with SAMPLED_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLED_FIELDS)
        w.writerows(replacements)
    print(f"appended to {SAMPLED_CSV}")
    print("\nNext: re-run exp/018 (cached → only the new pairs bill) to fetch their walk times.")


if __name__ == "__main__":
    main()
