"""Aggregate lexicon tokens by ward to surface area-based naming clusters.

For each unique title we extract:
  - its ward (parsed from the listing address)
  - its lexicon tokens (via 003's segmentation pipeline)

Then per (token, ward) we report:
  - count                — unique titles containing the token in that ward
  - token_share          — count / token_total (i.e. P(ward | token))
  - lift                 — P(ward | token) / P(ward), >1 means over-represented

Outputs:
  - data/009_aggregate_token_by_area/token_ward_long.csv
      one row per (token, ward) with count, token_share, lift.
  - data/009_aggregate_token_by_area/token_ward_lift_matrix.csv
      wide matrix: rows=tokens, cols=wards, values=lift; useful for eyeballing
      clusters or feeding into downstream clustering.
  - Console: for each token (above the count threshold), the top wards by lift
    and by raw count.

Counting unit matches 003 and the corrected 008: each unique title contributes
once per token occurrence; titles are deduped globally, listings/rooms are not.
"""

import csv
import importlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import click

SCRIPT_PATH = Path(__file__).resolve()
EXP_DIR = SCRIPT_PATH.parent
DATA_DIR = EXP_DIR.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
LONG_CSV = OUTPUT_DIR / "token_ward_long.csv"
MATRIX_CSV = OUTPUT_DIR / "token_ward_lift_matrix.csv"

MIN_TOKEN_COUNT = 50
TOP_WARDS_PER_TOKEN = 5
WARD_RE = re.compile(r"^東京都(.+?[区市町村])")

# Reuse 003's pipeline.
sys.path.insert(0, str(EXP_DIR))
_w = importlib.import_module("003_analyze_property_name_words")
KATAKANA_RE = _w.KATAKANA_RE
LEXICON_SET = _w.LEXICON_SET
ALIASES = _w.ALIASES
MIN_TOKEN_LEN = _w.MIN_TOKEN_LEN
ADDRESS_DIR = _w.ADDRESS_DIR
STATIONS_PATH = _w.STATIONS_PATH


def _title_lexicon_tokens(title: str, sorted_places: list[str]) -> list[str]:
    """Canonical lexicon tokens emitted by segmenting the title (per-occurrence)."""
    n = _w._normalize_title(title)
    if _w._is_descriptive(n):
        return []
    cleaned = _w._strip_tail(n, sorted_places)
    out: list[str] = []
    for chunk in KATAKANA_RE.findall(cleaned):
        for tok in _w._lexicon_split(chunk):
            if len(tok) < MIN_TOKEN_LEN:
                continue
            canonical = ALIASES.get(tok, tok)
            if canonical in LEXICON_SET:
                out.append(canonical)
    return out


def _parse_ward(address: str) -> str | None:
    a = unicodedata.normalize("NFKC", address)
    m = WARD_RE.match(a)
    return m.group(1) if m else None


def _load_unique_titles(path: Path) -> dict[str, str]:
    """{title: address}. First listing per title wins."""
    seen: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r.get("title")
            a = r.get("address")
            if not t or not a or t in seen:
                continue
            seen[t] = a
    return seen


@click.command()
@click.option(
    "--min-count",
    type=int,
    default=MIN_TOKEN_COUNT,
    help="Drop tokens with fewer than this many titles overall.",
)
@click.option(
    "--top-wards",
    type=int,
    default=TOP_WARDS_PER_TOKEN,
    help="How many wards to show per token in the console.",
)
def main(min_count: int, top_wards: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    places = _w._load_place_dict(ADDRESS_DIR, STATIONS_PATH)
    sorted_places = sorted(places, key=len, reverse=True)
    print(f"place dictionary: {len(places):,} entries")

    titles = _load_unique_titles(LISTINGS_PATH)
    print(f"unique titles: {len(titles):,}")

    ward_totals: Counter = Counter()
    token_totals: Counter = Counter()
    cell: dict[tuple[str, str], int] = defaultdict(int)
    skipped_no_ward = 0
    for title, address in titles.items():
        ward = _parse_ward(address)
        if ward is None:
            skipped_no_ward += 1
            continue
        ward_totals[ward] += 1
        for tok in _title_lexicon_tokens(title, sorted_places):
            token_totals[tok] += 1
            cell[(tok, ward)] += 1

    grand_total = sum(ward_totals.values())
    print(f"titles with parsed ward: {grand_total:,} (skipped {skipped_no_ward:,})")
    print(f"distinct wards: {len(ward_totals):,}, distinct tokens: {len(token_totals):,}")

    wards_sorted = sorted(ward_totals, key=lambda w: -ward_totals[w])
    tokens_sorted = [t for t, _ in token_totals.most_common() if token_totals[t] >= min_count]
    print(f"tokens passing min-count {min_count}: {len(tokens_sorted):,}")

    long_rows: list[dict] = []
    for tok in tokens_sorted:
        tok_total = token_totals[tok]
        for ward in wards_sorted:
            c = cell.get((tok, ward), 0)
            if c == 0:
                continue
            token_share = c / tok_total
            ward_share_overall = ward_totals[ward] / grand_total
            lift = token_share / ward_share_overall
            long_rows.append(
                {
                    "token": tok,
                    "ward": ward,
                    "count": c,
                    "token_share": round(token_share, 4),
                    "ward_share_overall": round(ward_share_overall, 4),
                    "lift": round(lift, 3),
                }
            )

    with LONG_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["token", "ward", "count", "token_share", "ward_share_overall", "lift"],
        )
        w.writeheader()
        w.writerows(long_rows)
    print(f"wrote long form: {LONG_CSV} ({len(long_rows):,} rows)")

    with MATRIX_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["token", "n", *wards_sorted])
        for tok in tokens_sorted:
            tok_total = token_totals[tok]
            row = [tok, tok_total]
            for ward in wards_sorted:
                c = cell.get((tok, ward), 0)
                if c == 0:
                    row.append("")
                    continue
                lift = (c / tok_total) / (ward_totals[ward] / grand_total)
                row.append(round(lift, 3))
            w.writerow(row)
    print(f"wrote lift matrix: {MATRIX_CSV} ({len(tokens_sorted):,} × {len(wards_sorted):,})")

    print("\n--- per-token top wards by LIFT (over-representation) ---")
    print(f"  {'token':<10}  {'n':>5}  wards (lift, count)")
    for tok in tokens_sorted:
        tok_total = token_totals[tok]
        ranked = []
        for ward in wards_sorted:
            c = cell.get((tok, ward), 0)
            if c == 0:
                continue
            lift = (c / tok_total) / (ward_totals[ward] / grand_total)
            ranked.append((ward, lift, c))
        ranked.sort(key=lambda x: -x[1])
        parts = [f"{w}({lift:.2f},{c})" for w, lift, c in ranked[:top_wards]]
        print(f"  {tok:<10}  {tok_total:>5,}  {' '.join(parts)}")


if __name__ == "__main__":
    main()
