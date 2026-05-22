"""X-post variant of the token-count bar chart (see 005 for the note version).

Same chart as 005, but the top 2 rows get taller, accent-colored bars so the
near-tie between rank 1 and 2 stands out in the X post. The note keeps the plain
005 chart; this variant is embedded only by 012 (post1_ranking).
Design reference: https://pudding.cool/2019/03/pop-music/
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click
import polars as pl

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
INPUT_CSV = PROJECT_ROOT / "data" / "003_analyze_property_name_words" / "token_counts.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_PNG = OUTPUT_DIR / "index.png"

DEFAULT_TOP_N = 10

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Top __TOP_N__ property-name tokens</title>
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
        --hot: #e0533d; /* red emphasis for the top 2 bars (matches the post's hot color) */
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
        fill: var(--hot);
        /* keep the dark border line from .bar so the red bars stay outlined */
      }

      .token {
        font-size: 14px;
        font-weight: 700;
        fill: var(--ink);
      }
      /* white text reads on the red top bars */
      .token.top,
      .count.top {
        fill: #ffffff;
      }

      .count {
        font-size: 14px;
        font-weight: 700;
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

      const W = 980;
      const ROW_H = 34;
      const TOP_ROW_H = 52; // taller bars for the top 2 so they stand out
      const TOP_N = 2;
      const ROW_GAP = 6;
      const RANK_COL = 44;
      const PAD = 14;
      const MARGIN_X = 24;
      const MARGIN_Y = 64;
      const BAR_AREA = W - RANK_COL;
      const totalW = W + MARGIN_X * 2;

      const rowH = (i) => (i < TOP_N ? TOP_ROW_H : ROW_H);
      const rowY = [];
      data.reduce((acc, _, i) => {
        rowY[i] = acc;
        return acc + rowH(i) + ROW_GAP;
      }, MARGIN_Y);
      const totalH = rowY[data.length - 1] + rowH(data.length - 1) + MARGIN_Y;
      const fmt = d3.format(",");
      const xScale = d3
        .scaleLinear()
        .domain([0, d3.max(data, (d) => d.count)])
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
        .attr("transform", (_, i) => `translate(${MARGIN_X}, ${rowY[i]})`);

      rows
        .append("text")
        .attr("class", "rank")
        .attr("x", RANK_COL - 14)
        .attr("y", (_, i) => rowH(i) / 2)
        .attr("dominant-baseline", "central")
        .attr("text-anchor", "end")
        .text((_, i) => String(i + 1).padStart(2, "0"));

      const barG = rows
        .append("g")
        .attr("transform", `translate(${RANK_COL}, 0)`);

      barG
        .append("rect")
        .attr("class", (_, i) => (i < TOP_N ? "bar top" : "bar"))
        .attr("x", 0)
        .attr("y", 0)
        .attr("height", (_, i) => rowH(i))
        .attr("width", (d) => xScale(d.count));

      barG
        .append("text")
        .attr("class", (_, i) => (i < TOP_N ? "token top" : "token"))
        .attr("x", PAD)
        .attr("y", (_, i) => rowH(i) / 2)
        .attr("dominant-baseline", "central")
        .text((d) => d.token);

      barG
        .append("text")
        .attr("class", (_, i) => (i < TOP_N ? "count top" : "count"))
        .attr("x", (d) => xScale(d.count) - PAD)
        .attr("y", (_, i) => rowH(i) / 2)
        .attr("dominant-baseline", "central")
        .attr("text-anchor", "end")
        .text((d) => fmt(d.count));
    </script>
  </body>
</html>
"""


@click.command()
@click.option(
    "-n",
    "--top-n",
    type=click.IntRange(min=1),
    default=DEFAULT_TOP_N,
    show_default=True,
    help="Number of top tokens to render.",
)
def main(top_n: int) -> None:
    df = pl.read_csv(INPUT_CSV).sort("count", descending=True).head(top_n)
    data_json = json.dumps(df.to_dicts(), ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json).replace("__TOP_N__", str(len(df)))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_HTML} (top {len(df)})")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector="#chart")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
