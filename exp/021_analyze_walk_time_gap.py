"""Analyze the gap between SUUMO's stated walk time and Google's actual walk time.

Input: data/020_finalize_walk_times/walk_times.csv — 9,906 resolved (building,
station) pairs, each with the SUUMO stated_min and Google's actual_min (Routes API
WALK duration), plus the route distance_m.

Sign convention: error_width_min = actual_min - stated_min.
  > 0  → real walk is LONGER than advertised  (SUUMO optimistic / understated)
  < 0  → real walk is shorter than advertised (SUUMO pessimistic)

Why weighting matters (from exp/017's design): the sample is station-stratified with
EQUAL allocation (~28 pairs/station), so the raw pair mean over-weights small
stations. The population-representative 23-ku figure weights each pair by its
station_total_pairs. We report both, and the weighted one is the headline.

SUUMO publishes walk time as 道路距離 ÷ 80m/min (rounded up). Using Google's actual
route distance under that same 80m/min rule lets us split the gap into:
  stated_min        — what SUUMO claims
  dist_implied_min  = distance_m / 80  — SUUMO's own rule on Google's real route
  actual_min        — Google's modeled walk duration (pace, crossings, waits)
so (stated → dist_implied) isolates SUUMO distance optimism and (dist_implied →
actual) isolates pace/crossing effects.

Outputs (data/021_analyze_walk_time_gap/): a printed report plus summary.json,
by_stated_min.csv, by_station.csv, by_ward.csv, error_distribution.csv.
No API calls — pure local analysis.
"""

from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
INPUT_CSV = DATA_DIR / "020_finalize_walk_times" / "walk_times.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem

SUUMO_METERS_PER_MIN = 80.0  # SUUMO convention: 道路距離80m = 徒歩1分 (rounded up)
# Plausibility cap (building-side). The sample is walk-only listings stated <=20min,
# i.e. <=1,600m under SUUMO's 80m/min rule. 2,500m = 1.56x that ceiling — generous for
# street detours, but tight enough to drop building Text Search mismatches to a
# same-named place (verified: "Muirfield"→Scotland ~13,000km; "高砂"→Hyogo). Tuned
# against the distance distribution: legit walks top out by the 97th pct (~1,780m),
# the median gap is invariant to the cap, and the mean stabilizes here once the >2.5km
# error tail is removed. NOTE: this per-pair cap cannot catch a mis-located STATION
# (e.g. 東高円寺→JR高円寺, all pairs offset ~630m); those are fixed by re-geocoding.
# Excluded rows are written out for audit.
MAX_PLAUSIBLE_DISTANCE_M = 2500
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


def main() -> None:
    raw = pd.read_csv(INPUT_CSV)
    raw = raw[raw["status"] == "ok"].copy()

    # Drop wrong-location geocoding artifacts before any statistics.
    outliers = raw[raw["distance_m"] > MAX_PLAUSIBLE_DISTANCE_M].copy()
    df = raw[raw["distance_m"] <= MAX_PLAUSIBLE_DISTANCE_M].copy()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not outliers.empty:
        outliers.assign(route_km=(outliers["distance_m"] / 1000).round(2)).sort_values(
            "distance_m", ascending=False
        ).to_csv(OUTPUT_DIR / "excluded_outliers.csv", index=False)
        print(
            f"excluded {len(outliers):,} geocode-artifact pairs "
            f"(distance_m > {MAX_PLAUSIBLE_DISTANCE_M:,}m, {len(outliers) / len(raw):.1%}) "
            f"→ excluded_outliers.csv"
        )

    # Derived metrics.
    df["abs_error_min"] = df["error_width_min"].abs()
    df["dist_implied_min"] = df["distance_m"] / SUUMO_METERS_PER_MIN
    df["google_pace_m_per_min"] = df["distance_m"] / df["actual_min"]
    w = df["station_total_pairs"]

    n = len(df)
    print(f"loaded {n:,} resolved pairs / {df['station'].nunique():,} stations / {df['ward'].nunique()} wards")
    print(f"distinct buildings: {df['building_place_id'].nunique():,}\n")

    # --- Topic 1a: overall, population-weighted headline ------------------
    weighted_width = _wmean(df["error_width_min"], w)
    weighted_rate = _wmean(df["error_rate"], w)
    print("=" * 64)
    print("OVERALL  (error_width = actual - stated; + means walk is LONGER)")
    print("=" * 64)
    print(f"  stated_min       mean {df['stated_min'].mean():5.2f}   median {df['stated_min'].median():5.1f}")
    print(f"  actual_min       mean {df['actual_min'].mean():5.2f}   median {df['actual_min'].median():5.2f}")
    ew = df["error_width_min"]
    print(f"  error_width_min  mean {ew.mean():+5.2f}   median {ew.median():+5.2f}")
    print(f"  abs_error_min    mean {df['abs_error_min'].mean():5.2f}   median {df['abs_error_min'].median():5.2f}")
    print(f"  error_rate       mean {df['error_rate'].mean():+6.1%}  median {df['error_rate'].median():+6.1%}")
    print("  --- population-weighted (by station_total_pairs) → 23-ku representative ---")
    print(f"  weighted error_width_min : {weighted_width:+.2f}")
    print(f"  weighted error_rate      : {weighted_rate:+.1%}")
    longer = (df["error_width_min"] > 0).mean()
    longer1 = (df["error_width_min"] > 1).mean()
    within1 = (df["abs_error_min"] <= 1).mean()
    shorter = (df["error_width_min"] < 0).mean()
    print(f"  share walk LONGER than stated (>0)      : {longer:5.1%}")
    print(f"  share LONGER by more than 1 min (>1)    : {longer1:5.1%}")
    print(f"  share within ±1 min                     : {within1:5.1%}")
    print(f"  share walk shorter than stated (<0)     : {shorter:5.1%}")

    # --- decomposition: SUUMO distance optimism vs pace -------------------
    print("\n  decomposition (mean minutes):")
    print(f"    stated_min                         : {df['stated_min'].mean():.2f}")
    print(f"    dist_implied_min (Google dist /80) : {df['dist_implied_min'].mean():.2f}   ← SUUMO rule on real route")
    print(f"    actual_min (Google duration)       : {df['actual_min'].mean():.2f}")
    pace = df["google_pace_m_per_min"].median()
    print(f"    Google pace median                 : {pace:.1f} m/min (SUUMO assumes 80)")

    # --- Topic 3: by stated_min -------------------------------------------
    by_min = (
        df.groupby("stated_min")
        .agg(
            n=("actual_min", "size"),
            actual_mean=("actual_min", "mean"),
            width_mean=("error_width_min", "mean"),
            rate_mean=("error_rate", "mean"),
            share_longer=("error_width_min", lambda s: (s > 0).mean()),
        )
        .round(3)
    )
    print("\n" + "=" * 64)
    print("BY STATED_MIN  (Topic 3)")
    print("=" * 64)
    print(by_min.to_string())

    # --- Topic 1b: by station ---------------------------------------------
    by_station = (
        df.groupby("station")
        .agg(
            n=("actual_min", "size"),
            ward=("ward", "first"),
            station_total_pairs=("station_total_pairs", "first"),
            stated_mean=("stated_min", "mean"),
            actual_mean=("actual_min", "mean"),
            width_mean=("error_width_min", "mean"),
            rate_mean=("error_rate", "mean"),
        )
        .round(3)
        .sort_values("width_mean", ascending=False)
    )
    print("\n" + "=" * 64)
    print("BY STATION  (Topic 1b) — most OPTIMISTic SUUMO (walk longest vs stated)")
    print("=" * 64)
    print(by_station.head(15).to_string())
    print("\n--- most PESSIMISTIC SUUMO (walk shortest vs stated) ---")
    print(by_station.tail(15).iloc[::-1].to_string())

    # --- Topic 2: by ward (population-weighted within ward) ---------------
    by_ward = (
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
    print("\n" + "=" * 64)
    print("BY WARD  (Topic 2) — sorted by population-weighted error_width")
    print("=" * 64)
    print(by_ward.to_string())

    # --- error distribution -----------------------------------------------
    dist = (
        pd.cut(df["error_width_min"], bins=ERROR_BINS, labels=ERROR_LABELS, right=False)
        .value_counts()
        .reindex(ERROR_LABELS)
    )
    dist_pct = (dist / n * 100).round(1)
    error_dist = pd.DataFrame({"count": dist, "pct": dist_pct})
    print("\n" + "=" * 64)
    print("ERROR_WIDTH DISTRIBUTION")
    print("=" * 64)
    print(error_dist.to_string())

    # --- write outputs ----------------------------------------------------
    by_min.to_csv(OUTPUT_DIR / "by_stated_min.csv")
    by_station.to_csv(OUTPUT_DIR / "by_station.csv")
    by_ward.to_csv(OUTPUT_DIR / "by_ward.csv")
    error_dist.to_csv(OUTPUT_DIR / "error_distribution.csv")

    summary = {
        "n_pairs": n,
        "n_excluded_outliers": int(len(outliers)),
        "max_plausible_distance_m": MAX_PLAUSIBLE_DISTANCE_M,
        "n_stations": int(df["station"].nunique()),
        "n_wards": int(df["ward"].nunique()),
        "stated_min_mean": round(df["stated_min"].mean(), 3),
        "actual_min_mean": round(df["actual_min"].mean(), 3),
        "error_width_mean": round(df["error_width_min"].mean(), 3),
        "error_width_median": round(df["error_width_min"].median(), 3),
        "error_width_weighted": round(weighted_width, 3),
        "error_rate_mean": round(df["error_rate"].mean(), 4),
        "error_rate_weighted": round(weighted_rate, 4),
        "share_longer_than_stated": round(float(longer), 4),
        "share_longer_by_over_1min": round(float(longer1), 4),
        "share_within_1min": round(float(within1), 4),
        "share_shorter_than_stated": round(float(shorter), 4),
        "dist_implied_min_mean": round(df["dist_implied_min"].mean(), 3),
        "google_pace_m_per_min_median": round(df["google_pace_m_per_min"].median(), 2),
    }
    pd.Series(summary).to_json(OUTPUT_DIR / "summary.json", indent=2, force_ascii=False)
    print(f"\nwrote summary.json + 4 CSVs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
