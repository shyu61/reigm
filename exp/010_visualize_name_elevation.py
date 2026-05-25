"""Render the per-token elevation results from 008 as a diverging vertical chart.

Each token gets a column anchored at the city-wide baseline. Above-baseline
tokens extend up (blue, 高台寄り); below-baseline tokens extend down (orange,
低地寄り). Sorted by mean elevation descending.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path

import click
import pandas as pd

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
INPUT_CSV = PROJECT_ROOT / "data" / "008_analyze_name_elevation" / "token_elevation.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_PNG = OUTPUT_DIR / "index.png"

DEFAULT_MIN_COUNT = 50
DEFAULT_TOKENS = ("ヒルズ", "スカイ", "ベイ", "リバー", "フォレスト", "ポート")

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>物件名トークン × エリア標高</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #eaf3fa;
        --ink: #0e1116;
        --muted: #5c6470;
        --high: #d98a6b;
        --low: #6aa9c4;
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
        max-width: 1180px;
        margin: 0 auto;
        padding: 64px 32px 80px;
      }

      #chart {
        display: block;
        overflow: visible;
      }

      .axis text {
        font-family:
          "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11px;
        fill: var(--muted);
      }

      .gridline {
        stroke: #cbd5dc;
        stroke-dasharray: 2 3;
        shape-rendering: crispEdges;
      }

      .baseline {
        stroke: var(--ink);
        stroke-width: 1.5;
        shape-rendering: crispEdges;
      }
      .baseline-label {
        font-family:
          "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11px;
        font-weight: 600;
        fill: var(--ink);
      }

      .bar {
        stroke: var(--border);
        stroke-width: 1;
        shape-rendering: crispEdges;
      }
      .bar.high {
        fill: url(#gradHigh);
      }
      .bar.low {
        fill: url(#gradLow);
      }

      .token {
        font-size: 11px;
        font-weight: 700;
        fill: var(--ink);
      }
      .value {
        font-family:
          "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 10px;
        font-weight: 600;
        fill: var(--ink);
        font-variant-numeric: tabular-nums;
        font-feature-settings: "tnum";
      }
    </style>
  </head>
  <body>
    <div class="page">
      <svg id="chart" preserveAspectRatio="xMinYMin meet"></svg>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const data = __DATA_JSON__;
      const baseline = __BASELINE__;

      const TARGET_INNER_W = 720;
      const COL_GAP = data.length <= 12 ? 12 : 4;
      const COL_W = Math.max(
        12,
        Math.min(54, (TARGET_INNER_W - (data.length - 1) * COL_GAP) / data.length),
      );
      const MARGIN_LEFT = 56;
      const MARGIN_RIGHT = 120;
      const MARGIN_TOP = 32;
      const MARGIN_BOTTOM = 32;
      const PLOT_H = 420;

      const EDGE_PAD = 18;
      const innerW = data.length * (COL_W + COL_GAP) - COL_GAP;
      const chartW = innerW + EDGE_PAD * 2;
      const totalW = MARGIN_LEFT + chartW + MARGIN_RIGHT;
      const totalH = MARGIN_TOP + PLOT_H + MARGIN_BOTTOM;

      const maxElev = d3.max(data, (d) => d.mean_elev_m);
      const minElev = d3.min(data, (d) => d.mean_elev_m);
      const upDelta = Math.ceil(maxElev - baseline + 1);
      const downDelta = Math.ceil(baseline - minElev + 1);
      const yScale = d3
        .scaleLinear()
        .domain([baseline - downDelta, baseline + upDelta])
        .range([MARGIN_TOP + PLOT_H, MARGIN_TOP]);

      const svg = d3
        .select("#chart")
        .attr("viewBox", `0 0 ${totalW} ${totalH}`)
        .attr("width", totalW)
        .attr("height", totalH);

      // --- gradient defs (light at baseline → saturated at tip) ---
      const HIGH_COLOR = "#d98a6b";
      const LOW_COLOR = "#6aa9c4";
      const defs = svg.append("defs");
      const gradHigh = defs
        .append("linearGradient")
        .attr("id", "gradHigh")
        .attr("x1", "0")
        .attr("y1", "0")
        .attr("x2", "0")
        .attr("y2", "1");
      gradHigh
        .append("stop")
        .attr("offset", "0%")
        .attr("stop-color", HIGH_COLOR)
        .attr("stop-opacity", 1);
      gradHigh
        .append("stop")
        .attr("offset", "100%")
        .attr("stop-color", HIGH_COLOR)
        .attr("stop-opacity", 0.2);
      const gradLow = defs
        .append("linearGradient")
        .attr("id", "gradLow")
        .attr("x1", "0")
        .attr("y1", "0")
        .attr("x2", "0")
        .attr("y2", "1");
      gradLow
        .append("stop")
        .attr("offset", "0%")
        .attr("stop-color", LOW_COLOR)
        .attr("stop-opacity", 0.2);
      gradLow
        .append("stop")
        .attr("offset", "100%")
        .attr("stop-color", LOW_COLOR)
        .attr("stop-opacity", 1);

      // --- y axis (gridlines + ticks) ---
      const yTicks = yScale.ticks(8);
      const axisG = svg.append("g").attr("class", "axis");
      yTicks.forEach((t) => {
        const y = yScale(t);
        axisG
          .append("line")
          .attr("class", "gridline")
          .attr("x1", MARGIN_LEFT)
          .attr("x2", MARGIN_LEFT + chartW)
          .attr("y1", y)
          .attr("y2", y);
        axisG
          .append("text")
          .attr("x", MARGIN_LEFT - 8)
          .attr("y", y)
          .attr("dominant-baseline", "central")
          .attr("text-anchor", "end")
          .text(`${t}m`);
      });

      // --- baseline line ---
      const baselineY = yScale(baseline);
      svg
        .append("line")
        .attr("class", "baseline")
        .attr("x1", MARGIN_LEFT)
        .attr("x2", MARGIN_LEFT + chartW)
        .attr("y1", baselineY)
        .attr("y2", baselineY);
      svg
        .append("text")
        .attr("class", "baseline-label")
        .attr("x", MARGIN_LEFT + chartW + 6)
        .attr("y", baselineY)
        .attr("dominant-baseline", "central")
        .text(`baseline ${baseline.toFixed(2)}m`);

      // --- bars (anchored at baseline; up if above, down if below) ---
      const cols = svg
        .selectAll("g.col")
        .data(data)
        .join("g")
        .attr("class", "col")
        .attr(
          "transform",
          (_, i) => `translate(${MARGIN_LEFT + EDGE_PAD + i * (COL_W + COL_GAP)}, 0)`,
        );

      cols
        .append("rect")
        .attr("class", (d) =>
          d.mean_elev_m >= baseline ? "bar high" : "bar low",
        )
        .attr("x", 0)
        .attr("y", (d) =>
          d.mean_elev_m >= baseline ? yScale(d.mean_elev_m) : baselineY,
        )
        .attr("width", COL_W)
        .attr("height", (d) => Math.abs(yScale(d.mean_elev_m) - baselineY));

      const fmtDelta = (v) => (v >= 0 ? "+" : "") + v.toFixed(1);
      cols
        .append("text")
        .attr("class", "value")
        .attr("x", COL_W / 2)
        .attr("y", (d) =>
          d.mean_elev_m >= baseline
            ? yScale(d.mean_elev_m) - 4
            : yScale(d.mean_elev_m) + 12,
        )
        .attr("text-anchor", "middle")
        .text((d) => fmtDelta(d.mean_vs_baseline_m));

      // Token labels sit just on the empty side of the baseline: below for
      // upward (positive) bars, above for downward (negative) bars. Use
      // `central` anchor (y is the text's vertical midpoint) so the same
      // numeric offset gives a visually identical gap on both sides.
      const TOKEN_GAP = 14;
      cols
        .append("text")
        .attr("class", "token")
        .attr("x", COL_W / 2)
        .attr("y", (d) =>
          d.mean_elev_m >= baseline
            ? baselineY + TOKEN_GAP
            : baselineY - TOKEN_GAP,
        )
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "central")
        .text((d) => d.token);
    </script>
  </body>
</html>
"""


@click.command()
@click.option(
    "--min-count",
    type=click.IntRange(min=1),
    default=DEFAULT_MIN_COUNT,
    show_default=True,
    help="Drop tokens with fewer than this many titles (ignored when --tokens is set).",
)
@click.option(
    "--tokens",
    default=",".join(DEFAULT_TOKENS),
    show_default=True,
    help="Comma-separated tokens to display. Pass empty string ('') to show all above --min-count.",
)
def main(min_count: int, tokens: str) -> None:
    df = pd.read_csv(INPUT_CSV)
    # Compute baseline from the full table before any filtering so the displayed
    # baseline matches 008's overall baseline regardless of which tokens we show.
    full_means = df["mean_elev_m"].tolist()
    full_deltas = df["mean_vs_baseline_m"].tolist()
    baseline = round(
        statistics.fmean(m - d for m, d in zip(full_means, full_deltas, strict=False)),
        2,
    )

    token_list = [t.strip() for t in tokens.split(",") if t.strip()]
    if token_list:
        df = df[df["token"].isin(token_list)]
    else:
        df = df[df["count"] >= min_count]
    df = df.sort_values("mean_elev_m", ascending=False)
    print(f"baseline = {baseline} m; tokens shown: {len(df):,}")

    data_json = json.dumps(df.to_dict(orient="records"), ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json).replace("__BASELINE__", str(baseline))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_HTML}")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector="#chart")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
