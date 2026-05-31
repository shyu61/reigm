"""Data-cleansing step: remove geocoding-artifact pairs from the walk-time dataset.

Input: data/020_finalize_walk_times/walk_times.csv (resolved pairs).

A pair is dropped when the building geocode is untrustworthy AND geometrically off.
`ratio` = Google route distance / (stated_min x 80m/min) — how many times longer the
real route is than SUUMO's stated time implies. A pair is an outlier if ANY of:
  (1) distance_m > MAX_PLAUSIBLE_DISTANCE_M — gross artifact (cross-prefecture /
      romaji-far match). 2,500m = 1.56x the 1,600m a 20min listing implies.
  (2) locality mismatch (resolved 区/市, 町名, or 丁目 differs from SUUMO's address)
      AND ratio >= RATIO_FLAG. The mismatch means a different place; the ratio gate
      spares boundary labels (a correct building tagged with the adjacent 区/町/丁目
      sits at ~the right spot, ratio ~1).
  (3) ratio >= EXTREME_RATIO regardless of locality — catches a wrong building within
      the SAME 町名/丁目 (e.g. matched a same-block restaurant), which (2) can't see.
Kept: locality matches at any ratio below EXTREME (genuine far-station optimism —
the core signal), and boundary-label mismatches at low ratio.
NOTE: a mis-located STATION is fixed upstream by re-geocoding, not here. A
non-residential resolved `type` is NOT used (correct buildings often geocode to a
ground-floor izakaya/salon at the right spot — the ratio already separates those).

Locality parsing: drop 日本/postal, then read the 区/市 (ward), the leading CJK run
after it (町名), and the first number after that (丁目). Romaji / unparseable values
return None and fall through to the distance backstop.

Outputs (data/022_clean_walk_times/):
  walk_times.csv        — kept pairs, original schema, sorted by error_width_min desc
  excluded_outliers.csv — removed pairs + diagnostic columns (q_*/r_*/ratio…)

Analysis lives in downstream scripts (e.g. exp/023). No API calls.
"""

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
INPUT_CSV = DATA_DIR / "020_finalize_walk_times" / "walk_times.csv"
BUILDING_CACHE = DATA_DIR / "018_fetch_walk_times" / "cache" / "building_geocode.jsonl"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
OUTPUT_CSV = OUTPUT_DIR / "walk_times.csv"  # cleaned: input minus excluded_outliers
EXCLUDED_CSV = OUTPUT_DIR / "excluded_outliers.csv"

MAX_PLAUSIBLE_DISTANCE_M = 2500
RATIO_FLAG = 1.5  # locality-mismatch pairs need this much geometric inconsistency
EXTREME_RATIO = 2.5  # this much alone is an outlier even when the locality matches

# Leading run of Japanese script (hiragana, katakana incl. ー, kanji, 々). Stops at
# the first digit / latin / dash, so "蒲田本町2丁目18-6" → "蒲田本町", "蒲田2" → "蒲田".
_CJK_RUN = re.compile(r"[぀-ヿ一-鿿々]+")
_AFTER_WARD = re.compile(r"[都道府県]?(.+?[区市])(.*)")
# the 区/市 token itself (after any 都道府県 prefix), e.g. "板橋区", "和光市".
_WARD = re.compile(r"[^\s0-9都道府県]+?[区市]")
# 町名 (CJK run) immediately followed by its 丁目 number, after the 区/市 boundary.
_CHOME = re.compile(r"[区市][぀-ヿ一-鿿々]+?(\d+)")


def _clean(addr: str) -> str:
    s = unicodedata.normalize("NFKC", addr)
    s = re.sub(r"^日本[、,\s]*", "", s)
    return re.sub(r"〒?\s*\d{3}-\d{4}", "", s)  # postal code (NNN-NNNN), not chome


def extract_ward(addr: str | None) -> str | None:
    if not addr:
        return None
    m = _WARD.search(_clean(addr))
    return m.group(0) if m else None


def extract_town(addr: str | None) -> str | None:
    if not addr:
        return None
    m = _AFTER_WARD.search(_clean(addr))
    if not m:
        return None
    run = _CJK_RUN.match(m.group(2).lstrip())
    if not run:
        return None
    town = run.group(0).replace("丁目", "").replace("ヶ", "ケ")
    # reject parse artifacts (a bare 都/県/区/市 token) and empties
    if not town or re.search(r"[都道府県区市]", town):
        return None
    return town


def extract_chome(addr: str | None) -> int | None:
    if not addr:
        return None
    m = _CHOME.search(_clean(addr))
    return int(m.group(1)) if m else None


def _building_loc_map(cache_path: Path) -> dict[str, tuple]:
    """key (title\\taddress) -> (resolved 区/市, 町名, 丁目) from the cache (last-wins)."""
    out: dict[str, tuple] = {}
    with cache_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            fmt = rec.get("formatted_address")
            out[rec["key"]] = (extract_ward(fmt), extract_town(fmt), extract_chome(fmt))
    return out


def annotate_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """Add geocode-quality columns + an `is_outlier` flag (does not filter).

    Requires columns: building_title, building_address, distance_m, stated_min.
    Adds: q_ward/r_ward, q_town/r_town, q_chome/r_chome, locality_mismatch, ratio,
    is_outlier.
    """
    df = df.copy()
    resolved = _building_loc_map(BUILDING_CACHE)
    key = df["building_title"] + "\t" + df["building_address"]
    df["q_ward"] = df["building_address"].map(extract_ward)
    df["r_ward"] = key.map(lambda k: (resolved.get(k) or (None, None, None))[0])
    df["q_town"] = df["building_address"].map(extract_town)
    df["r_town"] = key.map(lambda k: (resolved.get(k) or (None, None, None))[1])
    df["q_chome"] = df["building_address"].map(extract_chome)
    df["r_chome"] = key.map(lambda k: (resolved.get(k) or (None, None, None))[2])
    df["ratio"] = df["distance_m"] / (df["stated_min"] * 80.0)

    ward_mismatch = df["q_ward"].notna() & df["r_ward"].notna() & (df["q_ward"] != df["r_ward"])
    same_ward = df["q_ward"].notna() & df["r_ward"].notna() & (df["q_ward"] == df["r_ward"])
    town_known = df["q_town"].notna() & df["r_town"].notna()
    town_mismatch = same_ward & town_known & (df["q_town"] != df["r_town"])
    # same 区+町名 but different 丁目 (e.g. 碑文谷6 → 碑文谷4)
    chome_mismatch = (
        same_ward
        & town_known
        & (df["q_town"] == df["r_town"])
        & df["q_chome"].notna()
        & df["r_chome"].notna()
        & (df["q_chome"] != df["r_chome"])
    )
    df["locality_mismatch"] = ward_mismatch | town_mismatch | chome_mismatch

    gross = df["distance_m"] > MAX_PLAUSIBLE_DISTANCE_M
    wrong_locality = df["locality_mismatch"] & (df["ratio"] >= RATIO_FLAG)
    extreme = df["ratio"] >= EXTREME_RATIO
    df["is_outlier"] = gross | wrong_locality | extreme
    return df


def main() -> None:
    raw = pd.read_csv(INPUT_CSV)
    input_cols = list(raw.columns)  # preserve original schema for the cleaned output
    ok = raw[raw["status"] == "ok"].copy()

    annotated = annotate_outliers(ok)
    outliers = annotated[annotated["is_outlier"]].copy()
    kept = annotated[~annotated["is_outlier"]]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    kept[input_cols].sort_values("error_width_min", ascending=False).to_csv(OUTPUT_CSV, index=False)
    outliers.assign(route_km=(outliers["distance_m"] / 1000).round(2)).sort_values(
        "distance_m", ascending=False
    ).to_csv(EXCLUDED_CSV, index=False)

    gross = int((outliers["distance_m"] > MAX_PLAUSIBLE_DISTANCE_M).sum())
    other = len(outliers) - gross
    print(
        f"input {len(ok):,} ok pairs → kept {len(kept):,}, excluded {len(outliers):,} "
        f"({len(outliers) / len(ok):.1%}): {gross:,} gross-distance, {other:,} wrong-locality/extreme-ratio"
    )
    print(f"wrote walk_times.csv ({len(kept):,} rows) + excluded_outliers.csv to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
