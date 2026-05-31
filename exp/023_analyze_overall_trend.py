"""Charts for the SUUMO-vs-Google walk-time "全体傾向" (overall trend).

Reads the finalized, outlier-capped dataset and emits three article-ready figures
plus a KPI summary. Story arc: WHAT → DECOMPOSE → WHY.

  A. gap_distribution.png   — histogram of (actual - stated) minutes; median & mean
                              marked, the >0 "longer than stated" mass highlighted.
  B. decomposition_waterfall.png — mean gap split into a distance vs a pace part.
                              MEANS only: medians are not additive (median dist +
                              median pace != median total), means decompose exactly.
  C. walking_speed.png      — distribution of Google's effective pace (distance/
                              duration) vs SUUMO's assumed 80 m/min.

Sign: error_width_min = actual_min - stated_min (>0 = real walk is longer).
Decomposition (per pair, additive in means):
  distance part = distance_m/80 - stated_min   (SUUMO's own 80m/min rule on the real route)
  pace part     = actual_min   - distance_m/80 (extra time from real pace/crossings)

Caveats surfaced in the captions/summary:
  * SUUMO rounds stated time UP (ceil, ~+0.5min avg), which masks a small real
    distance under-measurement — that's why the distance part nets ~0.
  * Very short walks have fixed-overhead pace (low m/min) → the speed chart's left
    tail; the x-axis is clipped for readability (counts preserved in summary).

No API calls. Reads data/022_clean_walk_times/walk_times.csv.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager as fm

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
# Cleaned dataset from exp/022 (outliers already removed); pipeline: 018→020→021→022→023.
INPUT_CSV = DATA_DIR / "022_clean_walk_times" / "walk_times.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem

SUUMO_METERS_PER_MIN = 80.0

# --- distinctive type + palette (avoid the generic matplotlib default) -----
# Latin/numerals from Avenir Next, Japanese glyphs fall back to Hiragino Kaku Gothic.
FONT_LATIN = "/System/Library/Fonts/Avenir Next.ttc"
FONT_JP = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
FONT_JP_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

INK = "#14213d"  # primary text / structure
ACCENT = "#e4572e"  # the "gap" / pace driver (warm)
STEEL = "#3d6098"  # secondary (distance / cool)
NEUTRAL = "#b8c0cc"  # shorter-than-stated / de-emphasis
GRIDC = "#e6e8ec"
PAPER = "#fbfbf9"  # warm white background


def _setup_style() -> fm.FontProperties:
    for path in (FONT_LATIN, FONT_JP, FONT_JP_BOLD):
        fm.fontManager.addfont(path)
    latin = fm.FontProperties(fname=FONT_LATIN).get_name()
    jp = fm.FontProperties(fname=FONT_JP).get_name()
    plt.rcParams.update(
        {
            "font.family": [latin, jp],  # per-glyph fallback: Latin→Avenir, 日本語→Hiragino
            "font.size": 12,
            "axes.edgecolor": INK,
            "axes.linewidth": 0.8,
            "axes.facecolor": PAPER,
            "figure.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRIDC,
            "grid.linewidth": 0.9,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
        }
    )
    return fm.FontProperties(fname=FONT_JP_BOLD)


def _despine(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", visible=False)


def chart_gap_distribution(df: pd.DataFrame, k: dict, bold: fm.FontProperties) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    lo, hi, step = -6, 8, 0.5
    bins = [lo + i * step for i in range(int((hi - lo) / step) + 1)]
    # explicit bins drop out-of-range values (no false pile-up bar at the edges)
    counts, edges, patches = ax.hist(df["error_width_min"], bins=bins, edgecolor=PAPER, linewidth=0.6)
    for c, patch in zip(edges[:-1], patches, strict=True):
        patch.set_facecolor(ACCENT if c >= 0 else NEUTRAL)
    ax.axvline(0, color=INK, lw=1.0, ls=":")
    ax.axvline(k["median"], color=INK, lw=2.0)
    ax.axvline(k["mean"], color=STEEL, lw=2.0, ls="--")
    ymax = max(c for c in counts)
    ax.set_ylim(0, ymax * 1.15)
    ax.annotate(
        f"中央値 +{k['median']:.2f}分",
        xy=(k["median"], ymax * 0.92),
        xytext=(k["median"] + 1.3, ymax * 0.96),
        color=INK,
        fontsize=12,
        arrowprops={"arrowstyle": "-", "color": INK, "lw": 1},
    )
    ax.annotate(
        f"平均 +{k['mean']:.2f}分",
        xy=(k["mean"], ymax * 0.72),
        xytext=(k["mean"] + 1.6, ymax * 0.78),
        color=STEEL,
        fontsize=12,
        arrowprops={"arrowstyle": "-", "color": STEEL, "lw": 1},
    )
    ax.text(
        0.97,
        0.55,
        f"表記より長い\n{k['share_longer']:.0%}",
        transform=ax.transAxes,
        ha="right",
        va="center",
        color=ACCENT,
        fontproperties=bold,
        fontsize=20,
    )
    ax.set_title("実際の徒歩時間は表記より何分長いか", fontproperties=bold, fontsize=17, pad=34, loc="left")
    ax.text(
        0.0,
        1.015,
        f"SUUMO表記 vs Google徒歩ルート　n={k['n']:,}ペア（東京23区）",
        transform=ax.transAxes,
        fontsize=10.5,
        color="#5b6675",
    )
    ax.set_xlabel("実測 − 表記（分）")
    ax.set_ylabel("ペア数")
    ax.set_xlim(lo, hi)
    _despine(ax)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "gap_distribution.png", dpi=200)
    plt.close(fig)


def chart_decomposition(k: dict, bold: fm.FontProperties) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    stated, dist_c, pace_c, actual = k["stated_mean"], k["dist_comp_mean"], k["pace_comp_mean"], k["actual_mean"]
    labels = ["表記\n(SUUMO)", "距離の差", "歩行速度の差", "実測\n(Google)"]
    # waterfall: base heights for floating increment bars
    bases = [0, stated, stated + dist_c, 0]
    heights = [stated, dist_c, pace_c, actual]
    colors = [NEUTRAL, STEEL, ACCENT, INK]
    x = range(4)
    ax.bar(x, heights, bottom=bases, color=colors, width=0.62, edgecolor=PAPER, linewidth=0.8)
    # connector lines
    for i, lvl in enumerate([stated, stated + dist_c, actual]):
        ax.plot([i + 0.31, i + 1 - 0.31], [lvl, lvl], color="#8a93a3", lw=1, ls="--")
    # value labels (signed minutes; distance ≈ 0 so its share is omitted as misleading)
    lbl = {"ha": "center", "va": "bottom", "fontsize": 11}
    ax.text(0, stated + 0.12, f"{stated:.2f}分", **lbl)
    ax.text(1, stated + max(dist_c, 0) + 0.12, f"{dist_c:+.2f}分\n(距離)", **lbl)
    ax.text(2, stated + dist_c + pace_c + 0.12, f"{pace_c:+.2f}分\n(歩行速度)", **lbl)
    ax.text(3, actual + 0.12, f"{actual:.2f}分", **lbl)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("片道徒歩時間（分）")
    ax.set_ylim(0, actual * 1.18)
    ax.set_title("乖離の内訳：距離か、歩行速度か", fontproperties=bold, fontsize=17, pad=34, loc="left")
    ax.text(
        0.0,
        1.015,
        f"乖離 +{k['mean']:.2f}分 はほぼ全て歩行速度による（距離の差は {k['dist_comp_mean']:+.2f}分でほぼゼロ）",
        transform=ax.transAxes,
        fontsize=10.5,
        color="#5b6675",
    )
    _despine(ax)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "decomposition_waterfall.png", dpi=200)
    plt.close(fig)


def chart_speed(df: pd.DataFrame, k: dict, bold: fm.FontProperties) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    lo, hi, step = 20, 110, 2.5
    bins = [lo + i * step for i in range(int((hi - lo) / step) + 1)]
    counts, edges, patches = ax.hist(df["speed"], bins=bins, color=STEEL, edgecolor=PAPER, linewidth=0.5)
    for c, patch in zip(edges[:-1], patches, strict=True):
        if c >= 80:
            patch.set_facecolor(NEUTRAL)
    ymax = max(c for c in counts)
    ax.set_ylim(0, ymax * 1.15)
    ax.axvline(80, color=ACCENT, lw=2.2)
    ax.axvline(k["speed_median"], color=INK, lw=2.0, ls="--")
    ax.text(80 + 0.6, ymax * 0.96, "SUUMO前提\n80 m/分", color=ACCENT, fontproperties=bold, fontsize=12, va="top")
    ax.text(
        k["speed_median"] - 0.6,
        ymax * 0.72,
        f"中央値\n{k['speed_median']:.1f}",
        color=INK,
        fontsize=12,
        va="top",
        ha="right",
    )
    ax.text(
        0.03,
        0.55,
        f"{k['share_slower_than_80']:.1%} が\n80m/分より遅い",
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=STEEL,
        fontproperties=bold,
        fontsize=18,
    )
    ax.set_title("実際の歩行速度はSUUMO前提の80m/分より遅い", fontproperties=bold, fontsize=16, pad=34, loc="left")
    ax.text(
        0.0,
        1.015,
        f"Google徒歩ルートの実効速度（距離÷所要）　n={k['n']:,}ペア",
        transform=ax.transAxes,
        fontsize=10.5,
        color="#5b6675",
    )
    ax.set_xlabel("実効歩行速度（m/分）")
    ax.set_ylabel("ペア数")
    ax.set_xlim(lo, hi)
    _despine(ax)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "walking_speed.png", dpi=200)
    plt.close(fig)


def main() -> None:
    bold = _setup_style()
    df = pd.read_csv(INPUT_CSV)  # already cleaned by exp/022
    df["dist_implied"] = df["distance_m"] / SUUMO_METERS_PER_MIN
    df["dist_comp"] = df["dist_implied"] - df["stated_min"]
    df["pace_comp"] = df["actual_min"] - df["dist_implied"]
    df["speed"] = df["distance_m"] / df["actual_min"]

    mean_gap = df["error_width_min"].mean()
    k = {
        "n": len(df),
        "median": round(df["error_width_min"].median(), 3),
        "mean": round(mean_gap, 3),
        "share_longer": round((df["error_width_min"] > 0).mean(), 4),
        "median_rate": round(df["error_rate"].median(), 4),
        "aggregate_inflation": round(mean_gap / df["stated_min"].mean(), 4),
        "stated_mean": round(df["stated_min"].mean(), 3),
        "actual_mean": round(df["actual_min"].mean(), 3),
        "dist_comp_mean": round(df["dist_comp"].mean(), 3),
        "pace_comp_mean": round(df["pace_comp"].mean(), 3),
        "dist_share": round(df["dist_comp"].mean() / mean_gap, 4),
        "pace_share": round(df["pace_comp"].mean() / mean_gap, 4),
        "speed_median": round(df["speed"].median(), 2),
        "share_slower_than_80": round((df["speed"] < 80).mean(), 4),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    chart_gap_distribution(df, k, bold)
    chart_decomposition(k, bold)
    chart_speed(df, k, bold)
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(k, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote 3 charts + summary.json to {OUTPUT_DIR}")
    for key, val in k.items():
        print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
