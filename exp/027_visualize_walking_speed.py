"""Render the effective walking-speed distribution as a D3-powered HTML histogram.

An HTML/SVG re-make of 024's matplotlib `walking_speed.png`, built in the same
D3 → HTML → PNG idiom as 005/010/011/025/026: a string template with
__PLACEHOLDER__ substitutions, D3 v7 from the CDN, an SVG with a viewBox,
dashed gridlines + axes, and a conclusion-first callout.

No title/subtitle (per request) — just the n= eyebrow and the chart.

Story: speed = distance_m / actual_min (Google's effective pace). Almost every
walk is slower than SUUMO's assumed 80 m/分, so the bins left of 80 (実測が遅い)
carry the blue accent; the 80m/分 constant and the median are marked.

Bins are computed in Python (lo=20, hi=110, step=2.5, out-of-range dropped) so
the shape matches 024 exactly; KPIs reuse 024's definitions.

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

SUUMO_METERS_PER_MIN = 80.0

# Histogram extent (matches exp/024 so the binned shape is identical).
BIN_LO, BIN_HI, BIN_STEP = 20.0, 110.0, 2.5

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <title>実際の歩行速度は80m/分より遅い</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #eaf3fa;       /* airy light blue (matches 010/011/025/026) */
        --ink: #0e1116;      /* primary text / structure */
        --accent: #4e93bb;   /* 80m/分より遅い — the story (blue) */
        --warm: #d98a6b;     /* SUUMO前提 80m/分 marker (terracotta, matches 026) */
        --neutral: #b9c8d6;  /* 80m/分より速い / de-emphasis */
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
        fill: var(--muted);
      }
      .gridline {
        stroke: var(--grid);
        stroke-width: 1;
        stroke-dasharray: 2 3;
        shape-rendering: crispEdges;
      }

      .bar {
        shape-rendering: crispEdges;
        stroke: var(--border);
        stroke-width: 0.7;
      }
      .bar.slower {
        fill: var(--accent);
      }
      .bar.faster {
        fill: var(--neutral);
      }

      .marker-suumo {
        stroke: var(--warm);
        stroke-width: 2.4;
      }
      .marker-median {
        stroke: var(--ink);
        stroke-width: 2.0;
        stroke-dasharray: 7 5;
      }

      .anno {
        font-size: 14px;
        font-weight: 700;
      }
      .anno .val {
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-weight: 600;
      }
      .anno.suumo {
        fill: #c06a48;
      }
      .anno.median {
        fill: var(--ink);
      }

      .callout {
        font-size: 30px;
        font-weight: 900;
        fill: var(--accent);
      }
      .callout-sub {
        font-size: 15px;
        font-weight: 700;
        fill: var(--accent);
      }
    </style>
  </head>
  <body>
    <div class="page">
      <p class="eyebrow">
        <strong>n=__N__</strong>
      </p>
      <svg id="chart" preserveAspectRatio="xMinYMin meet"></svg>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const BINS = __BINS_JSON__; // [{x0, x1, count}]
      const K = __KPI_JSON__; // {median, share_slower}
      const X_LO = __X_LO__;
      const X_HI = __X_HI__;
      const SUUMO = __SUUMO__;

      const MARGIN = { top: 28, right: 28, bottom: 52, left: 64 };
      const PLOT_W = 880;
      const PLOT_H = 440;
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

      const x = d3.scaleLinear().domain([X_LO, X_HI]).range([0, PLOT_W]);
      const yMax = d3.max(BINS, (b) => b.count);
      const y = d3.scaleLinear().domain([0, yMax * 1.15]).range([PLOT_H, 0]);

      // --- y gridlines + ticks ---
      const yTicks = y.ticks(8).filter((t) => t <= yMax * 1.05);
      const axisG = plot.append("g").attr("class", "axis");
      yTicks.forEach((t) => {
        axisG
          .append("line")
          .attr("class", "gridline")
          .attr("x1", 0)
          .attr("x2", PLOT_W)
          .attr("y1", y(t))
          .attr("y2", y(t));
        axisG
          .append("text")
          .attr("x", -10)
          .attr("y", y(t))
          .attr("dominant-baseline", "central")
          .attr("text-anchor", "end")
          .text(d3.format(",")(t));
      });

      // --- bars (left of 80m/分 = slower, highlighted) ---
      plot
        .selectAll("rect.bar")
        .data(BINS)
        .join("rect")
        .attr("class", (b) => (b.x1 <= SUUMO ? "bar slower" : "bar faster"))
        .attr("x", (b) => x(b.x0))
        .attr("y", (b) => y(b.count))
        .attr("width", (b) => Math.max(0, x(b.x1) - x(b.x0)))
        .attr("height", (b) => PLOT_H - y(b.count));

      // --- x axis ticks ---
      const xTicks = d3.range(X_LO, X_HI + 1, 10);
      xTicks.forEach((t) => {
        axisG
          .append("text")
          .attr("x", x(t))
          .attr("y", PLOT_H + 22)
          .attr("text-anchor", "middle")
          .text(t);
      });

      // --- vertical markers (80m/分 前提, median) ---
      const marker = (cls, xv) =>
        plot
          .append("line")
          .attr("class", cls)
          .attr("x1", x(xv))
          .attr("x2", x(xv))
          .attr("y1", 0)
          .attr("y2", PLOT_H);
      marker("marker-median", K.median);
      marker("marker-suumo", SUUMO);

      // --- annotations (80m/分 to the right, median to the left) ---
      const suumoT = plot
        .append("text")
        .attr("class", "anno suumo")
        .attr("x", x(SUUMO) + 10)
        .attr("y", PLOT_H * 0.06)
        .attr("dominant-baseline", "hanging");
      suumoT.append("tspan").text("基準 ");
      suumoT.append("tspan").attr("class", "val").text(`${SUUMO}m/分`);

      const medT = plot
        .append("text")
        .attr("class", "anno median")
        .attr("x", x(K.median) - 10)
        .attr("y", PLOT_H * 0.28)
        .attr("text-anchor", "end")
        .attr("dominant-baseline", "hanging");
      medT.append("tspan").text("中央値 ");
      medT.append("tspan").attr("class", "val").text(`${K.median.toFixed(1)}`);

      // --- conclusion-first callout (upper-left, over the sparse low-speed tail) ---
      const cx = x(X_LO) + 18;
      plot
        .append("text")
        .attr("class", "callout")
        .attr("x", cx)
        .attr("y", PLOT_H * 0.30)
        .text(`${(K.share_slower * 100).toFixed(1)}%`);
      plot
        .append("text")
        .attr("class", "callout-sub")
        .attr("x", cx)
        .attr("y", PLOT_H * 0.30 + 24)
        .text("が 80m/分より遅い");

      // --- axis titles ---
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("x", PLOT_W / 2)
        .attr("y", PLOT_H + 48)
        .attr("text-anchor", "middle")
        .text("実効歩行速度（m/分）");
    </script>
  </body>
</html>
"""


def _histogram(values: pd.Series) -> list[dict[str, float]]:
    """Bin `values` into fixed [BIN_LO, BIN_HI) bins; out-of-range values are dropped."""
    n_bins = round((BIN_HI - BIN_LO) / BIN_STEP)
    edges = [BIN_LO + i * BIN_STEP for i in range(n_bins + 1)]
    counts = [0] * n_bins
    for v in values:
        if v < BIN_LO or v >= BIN_HI:
            continue
        idx = min(int((v - BIN_LO) / BIN_STEP), n_bins - 1)
        counts[idx] += 1
    return [{"x0": round(edges[i], 2), "x1": round(edges[i + 1], 2), "count": counts[i]} for i in range(n_bins)]


def main() -> None:
    df = pd.read_csv(INPUT_CSV)  # already cleaned by exp/022
    df["speed"] = df["distance_m"] / df["actual_min"]
    bins = _histogram(df["speed"])
    kpi = {
        "median": round(df["speed"].median(), 2),
        "share_slower": round((df["speed"] < SUUMO_METERS_PER_MIN).mean(), 4),
    }
    n = len(df)

    html = (
        HTML_TEMPLATE.replace("__BINS_JSON__", json.dumps(bins, ensure_ascii=False))
        .replace("__KPI_JSON__", json.dumps(kpi, ensure_ascii=False))
        .replace("__X_LO__", str(BIN_LO))
        .replace("__X_HI__", str(BIN_HI))
        .replace("__SUUMO__", str(SUUMO_METERS_PER_MIN))
        .replace("__N__", f"{n:,}")
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_HTML}")
    print(f"  n={n:,}  median={kpi['median']} m/min  slower_than_80={kpi['share_slower']:.1%}")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector=".page")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
