"""Per-topic breakdowns of the SUUMO-vs-Google walk-time gap.

Reads the cleaned dataset (exp/022) and emits a printed report + CSVs for the
research topics. The overall headline (Topic 1a) lives in exp/024; this covers:

  Topic 3  — by_stated_min : how the gap scales with the advertised time. Absolute
             error is ~flat, so the RATE shrinks as stated time grows.
  Topic 1b — by_station    : which stations are most/least optimistic. Ranked by the
             MEDIAN gap — with ~28 pairs/station the mean is swung by a stray pair,
             so median is the robust statistic (mean shown alongside).
  Topic 2  — by_ward       : area gradient. Reported population-weighted (by
             station_total_pairs) since the sample is equal-allocation per station.
  error_distribution       — how the per-pair gap is spread.

Sign: error_width_min = actual_min - stated_min (>0 = real walk is longer).
Weighting (exp/017 design): the sample gives every station ~28 pairs regardless of
size, so a raw mean over-weights small stations; weighting each pair by
station_total_pairs recovers the population-representative figure.

Outputs (data/023_analyze_topics/): by_stated_min.csv, by_station.csv, by_ward.csv,
error_distribution.csv. No API calls.
"""

from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
# Cleaned dataset from exp/022 (outliers removed); pipeline: 018→020→021→022→023.
INPUT_CSV = DATA_DIR / "022_clean_walk_times" / "walk_times.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem

# error_width buckets (minutes), left-closed; labels describe the SUUMO-vs-reality gap.
ERROR_BINS = [-100, -2, -1, 0, 1, 2, 3, 5, 100]
ERROR_LABELS = [
    "≤ -2 (much faster)",
    "-2..-1",
    "-1..0 (slightly faster)",
    "0..1 (slightly longer)",
    "1..2",
    "2..3",
    "3..5",
    "> 5 (much longer)",
]


def _wmean(values: pd.Series, weights: pd.Series) -> float:
    """Weighted mean (recovers the population estimate from the equal-allocation sample)."""
    return float((values * weights).sum() / weights.sum())


def by_stated_min(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("stated_min")
        .agg(
            n=("actual_min", "size"),
            actual_mean=("actual_min", "mean"),
            width_mean=("error_width_min", "mean"),
            width_median=("error_width_min", "median"),
            rate_mean=("error_rate", "mean"),
            rate_median=("error_rate", "median"),
            share_longer=("error_width_min", lambda s: (s > 0).mean()),
        )
        .round(3)
    )


def by_station(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("station")
        .agg(
            n=("actual_min", "size"),
            ward=("ward", "first"),
            station_total_pairs=("station_total_pairs", "first"),
            stated_mean=("stated_min", "mean"),
            actual_mean=("actual_min", "mean"),
            width_mean=("error_width_min", "mean"),
            width_median=("error_width_min", "median"),
            rate_median=("error_rate", "median"),
        )
        .round(3)
        .sort_values("width_median", ascending=False)  # median = robust ranking
    )


def by_ward(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("ward")
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "stations": g["station"].nunique(),
                    "width_mean": g["error_width_min"].mean(),
                    "width_weighted": _wmean(g["error_width_min"], g["station_total_pairs"]),
                    "rate_weighted": _wmean(g["error_rate"], g["station_total_pairs"]),
                    "share_longer": (g["error_width_min"] > 0).mean(),
                }
            ),
            include_groups=False,
        )
        .round(3)
        .sort_values("width_weighted", ascending=False)
    )


def error_distribution(df: pd.DataFrame) -> pd.DataFrame:
    dist = (
        pd.cut(df["error_width_min"], bins=ERROR_BINS, labels=ERROR_LABELS, right=False)
        .value_counts()
        .reindex(ERROR_LABELS)
    )
    return pd.DataFrame({"count": dist, "pct": (dist / len(df) * 100).round(1)})


def main() -> None:
    df = pd.read_csv(INPUT_CSV)  # already cleaned by exp/022
    print(f"loaded {len(df):,} pairs / {df['station'].nunique():,} stations / {df['ward'].nunique()} wards\n")

    bmin, bsta, bward, edist = by_stated_min(df), by_station(df), by_ward(df), error_distribution(df)

    print("=" * 70)
    print("BY STATED_MIN  (Topic 3) — absolute gap ~flat, rate shrinks with distance")
    print("=" * 70)
    print(bmin.to_string())
    print("\n" + "=" * 70)
    print("BY STATION  (Topic 1b) — most OPTIMISTIC (by median gap)")
    print("=" * 70)
    print(bsta.head(15).to_string())
    print("\n--- most PESSIMISTIC / accurate ---")
    print(bsta.tail(15).iloc[::-1].to_string())
    print("\n" + "=" * 70)
    print("BY WARD  (Topic 2) — population-weighted gap")
    print("=" * 70)
    print(bward.to_string())
    print("\n" + "=" * 70)
    print("ERROR_WIDTH DISTRIBUTION")
    print("=" * 70)
    print(edist.to_string())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bmin.to_csv(OUTPUT_DIR / "by_stated_min.csv")
    bsta.to_csv(OUTPUT_DIR / "by_station.csv")
    bward.to_csv(OUTPUT_DIR / "by_ward.csv")
    edist.to_csv(OUTPUT_DIR / "error_distribution.csv")
    print(f"\nwrote 4 CSVs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
