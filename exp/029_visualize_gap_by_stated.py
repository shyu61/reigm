"""Render the walk-time gap by *stated* minutes as a D3-powered HTML combo chart.

Built in the same D3 → HTML → PNG idiom as 025/026/027: a string template with
__PLACEHOLDER__ substitutions, D3 v7 from the CDN, an SVG with a viewBox, dashed
gridlines + axes. No title/subtitle (per the series convention) — just the n=
eyebrow and the chart.

Story (the two trends diverge — that *is* the point):
  * 乖離率（中央値, %）  …… bars, LEFT axis. Falls as stated time grows
                            (~25% at 1分 → ~8% at 20分): short walks are least reliable.
  * 絶対乖離（中央値, 分）…… line, RIGHT axis. RISES with stated time
                            (~0.25分 → ~1.5分): longer walks accrue more absolute slack.

So the rate shrinks not because the absolute error is flat, but because the
denominator (stated minutes) grows faster than the error does.

Median is used throughout (matches the article's main metric). No API calls.
Reads data/022_clean_walk_times/walk_times.csv.
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

MIN_N = 50  # drop stated-minute buckets thinner than this (all 1–20 clear it)

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <title>表記徒歩時間ごとの乖離</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #eaf3fa;       /* airy light blue (matches 025/026/027/028) */
        --ink: #0e1116;
        --accent: #4e93bb;   /* 乖離率（%）— bars */
        --warm: #d98a6b;     /* 絶対乖離（分）— line */
        --grid: #cbd5dc;
        --muted: #5c6470;
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
          "Inter", "Hiragino Sans", "Yu Gothic UI", system-ui, -apple-system,
          sans-serif;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
      }

      .page {
        max-width: 1040px;
        margin: 0 auto;
        padding: 56px 40px 64px;
      }

      .eyebrow {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 13.5px;
        font-weight: 500;
        color: var(--muted);
        margin: 0 0 4px;
      }
      .eyebrow strong {
        font-weight: 600;
        color: var(--ink);
      }

      #chart {
        width: 100%;
        height: auto;
        display: block;
        overflow: visible;
        margin-top: 8px;
      }

      .axis text {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
        font-weight: 500;
        fill: var(--muted);
      }
      .axis-title {
        font-size: 13px;
        font-weight: 700;
      }
      .gridline {
        stroke: var(--grid);
        stroke-width: 1;
        stroke-dasharray: 2 3;
        shape-rendering: crispEdges;
      }

      .bar {
        fill: var(--accent);
        shape-rendering: crispEdges;
        stroke: var(--border);
        stroke-width: 0.6;
      }

      .trend {
        fill: none;
        stroke: var(--warm);
        stroke-width: 2.6;
      }
      .dot {
        fill: var(--warm);
        stroke: #fff;
        stroke-width: 1;
      }

      .pt-label {
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 12.5px;
        font-weight: 600;
      }
      .pt-label.rate {
        fill: var(--accent);
      }
      .pt-label.abs {
        fill: #b9603f;
      }

      .legend text {
        font-size: 13px;
        font-weight: 600;
        fill: var(--ink);
      }
    </style>
  </head>
  <body>
    <div class="page">
      <p class="eyebrow"><strong>n=__N__</strong> ・ 表記分ごとの中央値</p>
      <svg id="chart" preserveAspectRatio="xMinYMin meet"></svg>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const ROWS = __ROWS_JSON__; // [{stated, n, width, rate}]

      const MARGIN = { top: 48, right: 70, bottom: 52, left: 62 };
      const PLOT_W = 820;
      const PLOT_H = 420;
      const totalW = MARGIN.left + PLOT_W + MARGIN.right;
      const totalH = MARGIN.top + PLOT_H + MARGIN.bottom;

      const svg = d3
        .select("#chart")
        .attr("viewBox", `0 0 ${totalW} ${totalH}`)
        .attr("width", totalW)
        .attr("height", totalH);
      const plot = svg
        .append("g")
        .attr("transform", `translate(${MARGIN.left}, ${MARGIN.top})`);

      const x = d3
        .scaleBand()
        .domain(ROWS.map((r) => r.stated))
        .range([0, PLOT_W])
        .paddingInner(0.28);
      const bw = x.bandwidth();

      const rateMax = d3.max(ROWS, (r) => r.rate);
      const absMax = d3.max(ROWS, (r) => r.width);
      const yRate = d3.scaleLinear().domain([0, rateMax * 1.12]).range([PLOT_H, 0]); // %
      const yAbs = d3.scaleLinear().domain([0, absMax * 1.12]).range([PLOT_H, 0]); // 分

      // --- gridlines + LEFT (rate %) axis ---
      const axisG = plot.append("g").attr("class", "axis");
      yRate.ticks(6).forEach((t) => {
        axisG
          .append("line")
          .attr("class", "gridline")
          .attr("x1", 0)
          .attr("x2", PLOT_W)
          .attr("y1", yRate(t))
          .attr("y2", yRate(t));
        axisG
          .append("text")
          .attr("x", -10)
          .attr("y", yRate(t))
          .attr("dominant-baseline", "central")
          .attr("text-anchor", "end")
          .text(`${Math.round(t * 100)}%`);
      });

      // --- RIGHT (absolute 分) axis ---
      yAbs.ticks(6).forEach((t) => {
        axisG
          .append("text")
          .attr("x", PLOT_W + 12)
          .attr("y", yAbs(t))
          .attr("dominant-baseline", "central")
          .attr("text-anchor", "start")
          .text(t.toFixed(1));
      });

      // --- bars: 乖離率（%）---
      plot
        .selectAll("rect.bar")
        .data(ROWS)
        .join("rect")
        .attr("class", "bar")
        .attr("x", (r) => x(r.stated))
        .attr("y", (r) => yRate(r.rate))
        .attr("width", bw)
        .attr("height", (r) => PLOT_H - yRate(r.rate));

      // --- x ticks (表記分) ---
      ROWS.forEach((r) => {
        axisG
          .append("text")
          .attr("x", x(r.stated) + bw / 2)
          .attr("y", PLOT_H + 22)
          .attr("text-anchor", "middle")
          .text(r.stated);
      });

      // --- line + dots: 絶対乖離（分）---
      const line = d3
        .line()
        .x((r) => x(r.stated) + bw / 2)
        .y((r) => yAbs(r.width));
      plot.append("path").datum(ROWS).attr("class", "trend").attr("d", line);
      plot
        .selectAll("circle.dot")
        .data(ROWS)
        .join("circle")
        .attr("class", "dot")
        .attr("cx", (r) => x(r.stated) + bw / 2)
        .attr("cy", (r) => yAbs(r.width))
        .attr("r", 3.2);

      // --- endpoint labels (anchor the two diverging trends) ---
      const first = ROWS[0];
      const last = ROWS[ROWS.length - 1];
      const rateLab = (r, dy) =>
        plot
          .append("text")
          .attr("class", "pt-label rate")
          .attr("x", x(r.stated) + bw / 2)
          .attr("y", yRate(r.rate) - dy)
          .attr("text-anchor", "middle")
          .text(`${Math.round(r.rate * 100)}%`);
      rateLab(first, 9);
      rateLab(last, 9);
      const absLab = (r, anchor, dx) =>
        plot
          .append("text")
          .attr("class", "pt-label abs")
          .attr("x", x(r.stated) + bw / 2 + dx)
          .attr("y", yAbs(r.width) - 10)
          .attr("text-anchor", anchor)
          .text(`${r.width.toFixed(2)}分`);
      absLab(first, "start", 6);
      absLab(last, "end", -6);

      // --- axis titles (colour-matched to series) ---
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("transform", `translate(${-46}, ${PLOT_H / 2}) rotate(-90)`)
        .attr("text-anchor", "middle")
        .attr("fill", "var(--accent)")
        .text("乖離率");
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("transform", `translate(${PLOT_W + 50}, ${PLOT_H / 2}) rotate(90)`)
        .attr("text-anchor", "middle")
        .attr("fill", "#b9603f")
        .text("絶対乖離（分）");
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("x", PLOT_W / 2)
        .attr("y", PLOT_H + 46)
        .attr("text-anchor", "middle")
        .attr("fill", "var(--muted)")
        .text("表記の徒歩時間（分）");

      // --- legend (top-left) ---
      const legend = plot.append("g").attr("class", "legend").attr("transform", "translate(0, -28)");
      legend
        .append("rect")
        .attr("x", 0)
        .attr("y", -11)
        .attr("width", 16)
        .attr("height", 12)
        .attr("fill", "var(--accent)");
      legend.append("text").attr("x", 22).attr("y", 0).text("乖離率（%）");
      legend
        .append("line")
        .attr("x1", 150)
        .attr("x2", 178)
        .attr("y1", -5)
        .attr("y2", -5)
        .attr("stroke", "var(--warm)")
        .attr("stroke-width", 2.6);
      legend
        .append("circle")
        .attr("cx", 164)
        .attr("cy", -5)
        .attr("r", 3.2)
        .attr("fill", "var(--warm)")
        .attr("stroke", "#fff");
      legend.append("text").attr("x", 184).attr("y", 0).text("絶対乖離（分）");
    </script>
  </body>
</html>
"""


def main() -> None:
    df = pd.read_csv(INPUT_CSV)  # already cleaned by exp/022
    g = df.groupby("stated_min").agg(
        n=("actual_min", "size"),
        width=("error_width_min", "median"),
        rate=("error_rate", "median"),
    )
    g = g[g["n"] >= MIN_N].sort_index()
    rows = [
        {"stated": int(s), "n": int(r.n), "width": round(float(r.width), 3), "rate": round(float(r.rate), 4)}
        for s, r in g.iterrows()
    ]
    n = int(g["n"].sum())

    html = HTML_TEMPLATE.replace("__ROWS_JSON__", json.dumps(rows, ensure_ascii=False)).replace("__N__", f"{n:,}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    lo, hi = rows[0], rows[-1]
    print(f"Saved: {OUTPUT_HTML}")
    print(f"  stated {lo['stated']}–{hi['stated']}分, n={n:,}")
    print(f"  rate:  {lo['rate']:.1%} → {hi['rate']:.1%}")
    print(f"  abs :  {lo['width']:.2f}分 → {hi['width']:.2f}分")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector=".page")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
