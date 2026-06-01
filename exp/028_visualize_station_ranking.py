"""Render the most "optimistic" stations as a D3-powered HTML bar ranking.

Which stations understate the walk the most? Built in the same D3 → HTML → PNG
idiom as 005 (design reference: white bars w/ heavy outline, in-bar labels, the
#1 row filled with the accent), reading the cleaned dataset directly.

Ranking statistic: per-station MEDIAN of (実測 − 表記). With ~28 pairs/station the
mean is swung by a stray pair, so the median is the robust choice (matches
exp/023's by_station ranking). Each bar is labelled with the station (区) on the
left and the median gap in minutes + the median rate (%) on the right. Top 12.

No API calls. Reads data/022_clean_walk_times/walk_times.csv.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
INPUT_CSV = PROJECT_ROOT / "data" / "022_clean_walk_times" / "walk_times.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_PNG = OUTPUT_DIR / "index.png"

TOP_N = 12
MIN_PAIRS = 20  # drop thin stations from the ranking (all sampled stations clear this)

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <title>表記より長い駅ランキング 上位__TOP_N__</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #e3eef6;
        --surface: #ffffff;
        --ink: #0e1116;
        --muted: #5c6470;
        --accent: #8fbed9;
        --border: #0e1116;
      }

      * {
        box-sizing: border-box;
      }

      html,
      body {
        margin: 0;
        padding: 0;
        background: var(--bg);
        color: var(--ink);
        font-family:
          "Inter",
          "Hiragino Sans",
          "Yu Gothic UI",
          system-ui,
          -apple-system,
          sans-serif;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
      }

      .page {
        max-width: 1040px;
        margin: 0 auto;
        padding: 64px 32px 80px;
      }

      #chart {
        width: 100%;
        height: auto;
        display: block;
        overflow: visible;
      }

      .rank {
        font-family:
          "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
        font-weight: 500;
        fill: var(--muted);
      }

      .bar {
        fill: var(--surface);
        stroke: var(--border);
        stroke-width: 2.5;
        shape-rendering: crispEdges;
      }
      .bar.top {
        fill: var(--accent);
      }

      .station {
        font-size: 14px;
        font-weight: 700;
        fill: var(--ink);
      }
      .ward {
        font-size: 12.5px;
        font-weight: 500;
        fill: var(--muted);
      }

      .value {
        font-size: 14px;
        font-weight: 700;
        fill: var(--ink);
        font-variant-numeric: tabular-nums;
        font-feature-settings: "tnum";
      }
      .value .rate {
        font-size: 12.5px;
        font-weight: 500;
        fill: var(--muted);
      }
    </style>
  </head>
  <body>
    <div class="page">
      <svg id="chart" preserveAspectRatio="xMinYMin meet"></svg>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const data = __DATA_JSON__; // [{station, ward, width_median, rate_median, n}]

      const W = 940;
      const ROW_H = 34;
      const ROW_GAP = 6;
      const RANK_COL = 44;
      const PAD = 14;
      const MARGIN_X = 24;
      const MARGIN_Y = 36;
      const BAR_AREA = W - RANK_COL;
      const totalW = W + MARGIN_X * 2;
      const totalH = data.length * (ROW_H + ROW_GAP) - ROW_GAP + MARGIN_Y * 2;

      const xScale = d3
        .scaleLinear()
        .domain([0, d3.max(data, (d) => d.width_median)])
        .range([0, BAR_AREA]);

      const svg = d3
        .select("#chart")
        .attr("viewBox", `0 0 ${totalW} ${totalH}`)
        .attr("width", totalW)
        .attr("height", totalH);

      const rows = svg
        .selectAll("g.row")
        .data(data)
        .join("g")
        .attr("class", "row")
        .attr(
          "transform",
          (_, i) => `translate(${MARGIN_X}, ${MARGIN_Y + i * (ROW_H + ROW_GAP)})`,
        );

      rows
        .append("text")
        .attr("class", "rank")
        .attr("x", RANK_COL - 14)
        .attr("y", ROW_H / 2)
        .attr("dominant-baseline", "central")
        .attr("text-anchor", "end")
        .text((_, i) => String(i + 1).padStart(2, "0"));

      const barG = rows
        .append("g")
        .attr("transform", `translate(${RANK_COL}, 0)`);

      barG
        .append("rect")
        .attr("class", (_, i) => (i === 0 ? "bar top" : "bar"))
        .attr("x", 0)
        .attr("y", 0)
        .attr("height", ROW_H)
        .attr("width", (d) => xScale(d.width_median));

      // station (区) — inside the bar, left
      barG
        .append("text")
        .attr("x", PAD)
        .attr("y", ROW_H / 2)
        .attr("dominant-baseline", "central")
        .call((t) => {
          t.append("tspan").attr("class", "station").text((d) => d.station);
          t.append("tspan").attr("class", "ward").text((d) => `  ${d.ward}`);
        });

      // +X.X分 +XX% — inside the bar, right
      barG
        .append("text")
        .attr("class", "value")
        .attr("x", (d) => xScale(d.width_median) - PAD)
        .attr("y", ROW_H / 2)
        .attr("dominant-baseline", "central")
        .attr("text-anchor", "end")
        .call((t) => {
          t.append("tspan").text((d) => `+${d.width_median.toFixed(1)}分`);
          t
            .append("tspan")
            .attr("class", "rate")
            .text((d) => `  +${Math.round(d.rate_median * 100)}%`);
        });
    </script>
  </body>
</html>
"""


def main() -> None:
    df = pd.read_csv(INPUT_CSV)  # already cleaned by exp/022
    by_station = (
        df.groupby("station")
        .agg(
            n=("actual_min", "size"),
            ward=("ward", "first"),
            width_median=("error_width_min", "median"),
            rate_median=("error_rate", "median"),
        )
        .reset_index()
    )
    eligible = by_station[by_station["n"] >= MIN_PAIRS]
    top = eligible.sort_values("width_median", ascending=False).head(TOP_N)

    rows = [
        {
            "station": r.station,
            "ward": r.ward,
            "width_median": round(float(r.width_median), 2),
            "rate_median": round(float(r.rate_median), 4),
            "n": int(r.n),
        }
        for r in top.itertuples()
    ]

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(rows, ensure_ascii=False)).replace(
        "__TOP_N__", str(TOP_N)
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_HTML}")
    print(f"  {len(eligible)} stations ≥ {MIN_PAIRS} pairs; top {TOP_N}:")
    for i, r in enumerate(rows, 1):
        pct = round(r["rate_median"] * 100)
        print(f"  {i:>2}. {r['station']}（{r['ward']}）  +{r['width_median']:.1f}分  +{pct}%")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector="#chart")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
