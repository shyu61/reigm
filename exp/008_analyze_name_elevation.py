"""Analyze the relationship between property-name tokens and area elevation.

For each listing we:
  1. Segment its title into lexicon tokens (reusing the pipeline from
     `003_analyze_property_name_words.py`).
  2. Look up the elevation of its address (from `007_fetch_address_elevation.py`).

Then per lexicon token we compute: count, mean/median elevation, and the gap
versus the overall baseline. Hypothesis check (e.g. スカイ・ヒルズ at higher
ground) shows up as a positive baseline gap.

Inputs:
  - data/001_fetch_suumo/listings.jsonl
  - data/007_fetch_address_elevation/address_elevation.csv

Outputs:
  - data/008_analyze_name_elevation/token_elevation.csv
  - Console: tokens ranked by mean elevation, plus baseline summary.
"""

import csv
import importlib
import json
import statistics
import sys
from pathlib import Path

import click

SCRIPT_PATH = Path(__file__).resolve()
EXP_DIR = SCRIPT_PATH.parent
DATA_DIR = EXP_DIR.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"
ELEVATION_CSV = DATA_DIR / "007_fetch_address_elevation" / "address_elevation.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
OUTPUT_CSV = OUTPUT_DIR / "token_elevation.csv"

MIN_TOKEN_COUNT = 20
TOP_N = 40

# Reuse the segmentation pipeline from 003.
sys.path.insert(0, str(EXP_DIR))
_w = importlib.import_module("003_analyze_property_name_words")
KATAKANA_RE = _w.KATAKANA_RE
LEXICON_SET = _w.LEXICON_SET
ALIASES = _w.ALIASES
MIN_TOKEN_LEN = _w.MIN_TOKEN_LEN
ADDRESS_DIR = _w.ADDRESS_DIR
STATIONS_PATH = _w.STATIONS_PATH


def _normalize_title(s: str) -> str:
    return _w._normalize_title(s)


def _is_descriptive(s: str) -> bool:
    return _w._is_descriptive(s)


def _strip_tail(s: str, sorted_places: list[str]) -> str:
    return _w._strip_tail(s, sorted_places)


def _lexicon_split(token: str) -> list[str]:
    return _w._lexicon_split(token)


def _load_elevations(path: Path) -> dict[str, float]:
    """Read address_elevation.csv → {address: elevation_m}, skipping unresolved rows."""
    out: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            elev = row.get("elevation_m", "")
            if elev == "" or elev is None:
                continue
            try:
                out[row["address"]] = float(elev)
            except ValueError:
                continue
    return out


def _title_lexicon_tokens(title: str, sorted_places: list[str]) -> set[str]:
    """Return the set of canonical lexicon tokens contained in the (normalized, stripped) title."""
    n = _normalize_title(title)
    if _is_descriptive(n):
        return set()
    cleaned = _strip_tail(n, sorted_places)
    tokens: set[str] = set()
    for chunk in KATAKANA_RE.findall(cleaned):
        for tok in _lexicon_split(chunk):
            if len(tok) < MIN_TOKEN_LEN:
                continue
            canonical = ALIASES.get(tok, tok)
            if canonical in LEXICON_SET:
                tokens.add(canonical)
    return tokens


def _iter_listing_records(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r.get("title")
            a = r.get("address")
            if t and a:
                yield t, a


def _summarize(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


@click.command()
@click.option("--min-count", type=int, default=MIN_TOKEN_COUNT, help="Drop tokens with fewer than this many listings.")
@click.option("--top-n", type=int, default=TOP_N, help="How many tokens to print on each leaderboard.")
def main(min_count: int, top_n: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    elev_by_addr = _load_elevations(ELEVATION_CSV)
    print(f"loaded elevations for {len(elev_by_addr):,} addresses")

    places = _w._load_place_dict(ADDRESS_DIR, STATIONS_PATH)
    sorted_places = sorted(places, key=len, reverse=True)
    print(f"place dictionary: {len(places):,} entries")

    token_elevs: dict[str, list[float]] = {}
    all_elevs: list[float] = []
    matched = 0
    skipped_no_elev = 0
    for title, address in _iter_listing_records(LISTINGS_PATH):
        elev = elev_by_addr.get(address)
        if elev is None:
            skipped_no_elev += 1
            continue
        all_elevs.append(elev)
        tokens = _title_lexicon_tokens(title, sorted_places)
        if not tokens:
            continue
        matched += 1
        for tok in tokens:
            token_elevs.setdefault(tok, []).append(elev)

    print(f"listings with elevation: {len(all_elevs):,} (skipped {skipped_no_elev:,})")
    print(f"listings with >=1 lexicon token: {matched:,}")

    baseline = _summarize(all_elevs)
    print(
        f"\nbaseline elevation — mean {baseline['mean']:.2f} m, "
        f"median {baseline['median']:.2f} m, stdev {baseline['stdev']:.2f} m"
    )

    rows: list[dict] = []
    for tok, vals in token_elevs.items():
        if len(vals) < min_count:
            continue
        s = _summarize(vals)
        rows.append(
            {
                "token": tok,
                "count": s["count"],
                "mean_elev_m": round(s["mean"], 3),
                "median_elev_m": round(s["median"], 3),
                "stdev_elev_m": round(s["stdev"], 3),
                "mean_vs_baseline_m": round(s["mean"] - baseline["mean"], 3),
            }
        )

    rows.sort(key=lambda r: r["mean_elev_m"], reverse=True)

    print(f"\n--- top {top_n} tokens by MEAN elevation (count>={min_count}) ---")
    print(f"  {'rank':>4}  {'n':>6}  {'mean_m':>8}  {'Δbase':>8}  token")
    for rank, r in enumerate(rows[:top_n], 1):
        print(
            f"  {rank:>4}  {r['count']:>6,}  {r['mean_elev_m']:>8.2f}  {r['mean_vs_baseline_m']:>+8.2f}  {r['token']}"
        )

    print(f"\n--- bottom {top_n} tokens by MEAN elevation (count>={min_count}) ---")
    print(f"  {'rank':>4}  {'n':>6}  {'mean_m':>8}  {'Δbase':>8}  token")
    for rank, r in enumerate(rows[-top_n:][::-1], 1):
        print(
            f"  {rank:>4}  {r['count']:>6,}  {r['mean_elev_m']:>8.2f}  {r['mean_vs_baseline_m']:>+8.2f}  {r['token']}"
        )

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["token", "count", "mean_elev_m", "median_elev_m", "stdev_elev_m", "mean_vs_baseline_m"],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
