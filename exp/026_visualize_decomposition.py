"""Render the walk-time gap decomposition as a D3-powered HTML waterfall.

An HTML/SVG re-make of 024's matplotlib `decomposition_waterfall.png`, in the same
D3 → HTML → PNG idiom as 005/010/011/025: a string template with __PLACEHOLDER__
substitutions, D3 v7, an SVG with a viewBox, dashed gridlines + axes.

Reframed vs 024 to remove the "implied 80m/min" confusion:

  * 024 drew an ABSOLUTE waterfall 表記(9.03) → 実測(9.89), so the two decomposition
    steps were tiny slivers on a 0→9.9 axis and the 80m/min bridge was only implied.
  * Here we draw a GAP waterfall: everything is measured as minutes RELATIVE to 表記
    (= 0 baseline), so the steps fill the plot and are legible. The 80m/min constant
    is written out explicitly in each bar's sub-label and the footnote.

Identity (means only — medians are not additive):
    実測 − 表記  =  (実測距離/80 − 表記)  +  (実測 − 実測距離/80)
       +0.86分   =        距離の差          +        歩行速度の差
                 =        −0.31分           +        +1.17分

The distance part nets ~0 because the real route is longer than the stated distance,
but SUUMO ceils stated minutes UP — the two roughly cancel. So the gap is, in
substance, almost entirely a walking-pace effect (real pace < 80m/min).

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

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <title>乖離の内訳：距離か、歩行速度か</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #eaf3fa;       /* airy light blue (matches 010/011/025) */
        --ink: #0e1116;      /* primary text / structure */
        --accent: #4e93bb;   /* 歩行速度の差 — the driver (blue) */
        --warm: #d98a6b;     /* 距離の差 — the ~0 part (terracotta, matches 010) */
        --total: #2c4a63;    /* 乖離合計 (dark steel) */
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
      .bar.distance { fill: var(--warm); }
      .bar.pace { fill: var(--accent); }
      .bar.total { fill: var(--total); }

      .connector {
        stroke: #8a93a3;
        stroke-width: 1;
        stroke-dasharray: 4 4;
      }

      .zeroline {
        stroke: var(--ink);
        stroke-width: 1.6;
        shape-rendering: crispEdges;
      }

      .collabel {
        font-size: 15px;
        font-weight: 700;
        fill: var(--ink);
      }
      .colsub {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11px;
        font-weight: 500;
        fill: var(--muted);
      }
      .value {
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 16px;
        font-weight: 600;
      }
      .value.distance { fill: #b9603f; }
      .value.pace { fill: var(--accent); }
      .value.total { fill: var(--total); }

      .insight {
        font-size: 14px;
        font-weight: 800;
        fill: var(--accent);
      }

      .footnote {
        max-width: 880px;
        margin: 14px auto 0;
        font-size: 12.5px;
        line-height: 1.7;
        color: var(--muted);
      }
      .footnote b { color: var(--ink); font-weight: 700; }
    </style>
  </head>
  <body>
    <div class="page">
      <p class="eyebrow">
        <strong>n=__N__</strong>
      </p>
      <svg id="chart" preserveAspectRatio="xMinYMin meet"></svg>
      <p class="footnote">
        <b>80m/分</b> は徒歩分数（表記）の算出に使われる前提速度。
      </p>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const D = __DATA_JSON__; // {distance, pace, gap, stated, actual, bridge}

      // Build the gap waterfall (running total starts at 0 = 表記 baseline).
      const STEPS = [
        {
          key: "distance",
          label: "距離の差",
          sub: "実測距離 ÷ 80 − 表記",
          value: D.distance,
          start: 0,
          end: D.distance,
        },
        {
          key: "pace",
          label: "歩行速度の差",
          sub: "実測 − 実測距離 ÷ 80",
          value: D.pace,
          start: D.distance,
          end: D.distance + D.pace,
        },
        {
          key: "total",
          label: "乖離（実測 − 表記）",
          sub: "= 距離の差 + 歩行速度の差",
          value: D.gap,
          start: 0,
          end: D.gap,
        },
      ];

      const MARGIN = { top: 40, right: 36, bottom: 84, left: 72 };
      const PLOT_W = 820;
      const PLOT_H = 430;
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
        .domain(STEPS.map((s) => s.key))
        .range([0, PLOT_W])
        .paddingInner(0.42)
        .paddingOuter(0.32);
      const bw = x.bandwidth();

      const lo = d3.min(STEPS, (s) => Math.min(s.start, s.end));
      const hi = d3.max(STEPS, (s) => Math.max(s.start, s.end));
      const y = d3
        .scaleLinear()
        .domain([lo - 0.28, hi + 0.22])
        .range([PLOT_H, 0]);

      // --- y gridlines + ticks (signed minutes; 0 = 表記) ---
      const axisG = plot.append("g").attr("class", "axis");
      const fmtTick = (t) => (t === 0 ? "0" : d3.format("+.1f")(t));
      y.ticks(7).forEach((t) => {
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
          .text(fmtTick(t));
      });

      // --- connector lines linking running totals ---
      const connect = (xa, xb, lvl) =>
        plot
          .append("line")
          .attr("class", "connector")
          .attr("x1", xa)
          .attr("x2", xb)
          .attr("y1", y(lvl))
          .attr("y2", y(lvl));
      connect(x("distance") + bw, x("pace"), D.distance); // after 距離 → into 歩行速度
      connect(x("pace") + bw, x("total"), D.gap); // after 歩行速度 → into 合計

      // --- bars ---
      const cols = plot
        .selectAll("g.col")
        .data(STEPS)
        .join("g")
        .attr("class", "col")
        .attr("transform", (s) => `translate(${x(s.key)}, 0)`);

      cols
        .append("rect")
        .attr("class", (s) => `bar ${s.key}`)
        .attr("x", 0)
        .attr("y", (s) => y(Math.max(s.start, s.end)))
        .attr("width", bw)
        .attr("height", (s) => Math.abs(y(s.start) - y(s.end)));

      // --- value labels (above for upward, below for downward) ---
      const fmtVal = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "分";
      cols
        .append("text")
        .attr("class", (s) => `value ${s.key}`)
        .attr("x", bw / 2)
        .attr("text-anchor", "middle")
        .attr("y", (s) =>
          s.end >= s.start ? y(Math.max(s.start, s.end)) - 9 : y(s.end) + 20,
        )
        .text((s) => fmtVal(s.value));

      // --- column labels + mono sub-labels (below the plot) ---
      cols
        .append("text")
        .attr("class", "collabel")
        .attr("x", bw / 2)
        .attr("y", PLOT_H + 30)
        .attr("text-anchor", "middle")
        .text((s) => s.label);
      cols
        .append("text")
        .attr("class", "colsub")
        .attr("x", bw / 2)
        .attr("y", PLOT_H + 50)
        .attr("text-anchor", "middle")
        .text((s) => s.sub);

      // --- zero baseline (= 表記) drawn last so it sits on top ---
      plot
        .append("line")
        .attr("class", "zeroline")
        .attr("x1", 0)
        .attr("x2", PLOT_W)
        .attr("y1", y(0))
        .attr("y2", y(0));

      // --- one-line insight over the pace bar ---
      plot
        .append("text")
        .attr("class", "insight")
        .attr("x", x("pace") + bw / 2)
        .attr("y", y(D.distance + D.pace) - 34)
        .attr("text-anchor", "middle")
        .text("乖離のほぼ全ては歩行速度");

      // --- y axis title ---
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("transform", `translate(${-52}, ${PLOT_H / 2}) rotate(-90)`)
        .attr("text-anchor", "middle")
        .text("表記からの差（分）");
    </script>
  </body>
</html>
"""


def main() -> None:
    df = pd.read_csv(INPUT_CSV)  # already cleaned by exp/022
    stated = df["stated_min"].mean()
    bridge = (df["distance_m"] / SUUMO_METERS_PER_MIN).mean()
    actual = df["actual_min"].mean()
    data = {
        "distance": round(bridge - stated, 4),
        "pace": round(actual - bridge, 4),
        "gap": round(actual - stated, 4),
        "stated": round(stated, 4),
        "actual": round(actual, 4),
        "bridge": round(bridge, 4),
    }
    n = len(df)

    html = (
        HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
        .replace("__N__", f"{n:,}")
        .replace("__GAP__", f"{data['gap']:.2f}")
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_HTML}")
    print(f"  gap=+{data['gap']:.2f}  =  distance {data['distance']:+.2f}  +  pace {data['pace']:+.2f}")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector=".page")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
