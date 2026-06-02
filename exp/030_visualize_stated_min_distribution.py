"""Render the distribution of listings by *stated* walk minutes as a D3 bar chart.

Same D3 → HTML → PNG idiom as 025–029: a string template with __PLACEHOLDER__
substitutions, D3 v7 from the CDN, an SVG with a viewBox, dashed gridlines + axes.

One row per *room*, so the same building appears many times. We collapse rooms
into one property by deduping on (title, address) — the building is counted once.

A property's `access` lists one or more stations, e.g. "ＪＲ常磐線/金町駅 歩8分".
We render TWO views (each its own HTML + PNG under data/<stem>/):
  nearest_station — one data point per property, its closest walkable station
                    (min 歩分). n = property count.
  every_station   — one data point per walkable station, so a property with 3
                    stations contributes 3. n = station-access count.
Properties with no walk-time access entry (bus-only, etc.) are dropped.

Each chart is a histogram: x = stated_min (分), y = count. Minutes beyond MAX_MIN
are lumped into a trailing "MAX_MIN+" overflow bar so the long tail doesn't
stretch the axis.

No API calls. Reads data/001_fetch_suumo/listings.jsonl.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
INPUT_JSONL = PROJECT_ROOT / "data" / "001_fetch_suumo" / "listings.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem

WALK_RE = re.compile(r"歩(\d+)分")
MAX_MIN = 20  # minutes beyond this collapse into a single "20+" overflow bar

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <title>表記徒歩時間の分布</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Zen+Kaku+Gothic+New:wght@500;700;900&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #eaf3fa;       /* airy light blue (matches the 025–029 series) */
        --ink: #0e1116;
        --accent: #4e93bb;   /* bars */
        --accent-2: #d98a6b; /* overflow / median marker */
        --grid: #cbd5dc;
        --muted: #5c6470;
        --border: #0e1116;
      }

      * { box-sizing: border-box; }

      html, body {
        margin: 0;
        padding: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: "Zen Kaku Gothic New", "Hiragino Sans", sans-serif;
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
      .eyebrow strong { font-weight: 600; color: var(--ink); }

      .headline {
        font-family: "Zen Kaku Gothic New", sans-serif;
        font-weight: 900;
        font-size: 26px;
        letter-spacing: 0.01em;
        margin: 2px 0 0;
      }

      #chart {
        width: 100%;
        height: auto;
        display: block;
        overflow: visible;
        margin-top: 10px;
      }

      .axis text {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
        font-weight: 500;
        fill: var(--muted);
      }
      .axis-title {
        font-family: "Space Grotesk", sans-serif;
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
        fill: var(--accent);
        shape-rendering: crispEdges;
        stroke: var(--border);
        stroke-width: 0.6;
      }
      .bar.overflow { fill: var(--accent-2); }
    </style>
  </head>
  <body>
    <div class="page">
      <p class="eyebrow"><strong>n=__N__</strong> ・ __EYEBROW_SUFFIX__</p>
      <h1 class="headline">__HEADLINE__</h1>
      <svg id="chart" preserveAspectRatio="xMinYMin meet"></svg>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const ROWS = __ROWS_JSON__; // [{label, count, overflow}]

      const MARGIN = { top: 36, right: 28, bottom: 54, left: 86 };
      const PLOT_W = 900;
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
        .domain(ROWS.map((r) => r.label))
        .range([0, PLOT_W])
        .paddingInner(0.22);
      const bw = x.bandwidth();

      const yMax = d3.max(ROWS, (r) => r.count);
      const y = d3.scaleLinear().domain([0, yMax * 1.08]).range([PLOT_H, 0]);

      // --- gridlines + Y axis (count) ---
      const axisG = plot.append("g").attr("class", "axis");
      y.ticks(6).forEach((t) => {
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

      // --- bars ---
      plot
        .selectAll("rect.bar")
        .data(ROWS)
        .join("rect")
        .attr("class", (r) => (r.overflow ? "bar overflow" : "bar"))
        .attr("x", (r) => x(r.label))
        .attr("y", (r) => y(r.count))
        .attr("width", bw)
        .attr("height", (r) => PLOT_H - y(r.count));

      // --- x ticks (one per bar) ---
      ROWS.forEach((r) => {
        axisG
          .append("text")
          .attr("x", x(r.label) + bw / 2)
          .attr("y", PLOT_H + 22)
          .attr("text-anchor", "middle")
          .text(r.label);
      });

      // --- axis titles ---
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("transform", `translate(${-68}, ${PLOT_H / 2}) rotate(-90)`)
        .attr("text-anchor", "middle")
        .text("__YAXIS__");
      plot
        .append("text")
        .attr("class", "axis-title")
        .attr("x", PLOT_W / 2)
        .attr("y", PLOT_H + 48)
        .attr("text-anchor", "middle")
        .text("表記の徒歩時間（分）");
    </script>
  </body>
</html>
"""


# Two views, both deduped to unique properties first:
#   nearest — one point per property, its closest walkable station (min 歩分)
#   every   — one point per walkable station, so a 3-station property gives 3 points
VIEWS = {
    "nearest": {
        "stem": "nearest_station",
        "eyebrow": "最寄り駅までの表記徒歩時間（分）",
        "headline": "表記徒歩時間ごとの物件数分布",
        "yaxis": "物件数",
        "n_label": "properties w/ walk time",
    },
    "every": {
        "stem": "every_station",
        "eyebrow": "全アクセス駅の表記徒歩時間（分）",
        "headline": "表記徒歩時間ごとの駅アクセス数分布",
        "yaxis": "駅アクセス数",
        "n_label": "station accesses",
    },
}


def parse_walk_mins(record: dict) -> list[int]:
    """Return the 歩X分 walk time of every access entry (one per station)."""
    mins: list[int] = []
    for entry in record.get("access") or []:
        m = WALK_RE.search(entry)
        if m:
            mins.append(int(m.group(1)))
    return mins


def render_view(view: dict, all_minutes: list[int]) -> None:
    """Render one histogram (HTML + PNG) for the given minute samples."""
    counts: dict[int, int] = {}
    for m in all_minutes:
        counts[m] = counts.get(m, 0) + 1
    n = len(all_minutes)

    # Build display rows: 1..MAX_MIN-1 individually, then a "MAX_MIN+" bucket (>= MAX_MIN).
    rows = []
    for minute in range(1, MAX_MIN):
        rows.append({"label": str(minute), "count": counts.get(minute, 0), "overflow": False})
    overflow_count = sum(c for minute, c in counts.items() if minute >= MAX_MIN)
    if overflow_count:
        rows.append({"label": f"{MAX_MIN}+", "count": overflow_count, "overflow": False})

    # Median / mean of the raw (uncapped) minutes.
    sorted_mins = sorted(all_minutes)
    mid = n // 2
    median = sorted_mins[mid] if n % 2 else (sorted_mins[mid - 1] + sorted_mins[mid]) / 2
    mean = sum(all_minutes) / n

    html = (
        HTML_TEMPLATE.replace("__ROWS_JSON__", json.dumps(rows, ensure_ascii=False))
        .replace("__N__", f"{n:,}")
        .replace("__EYEBROW_SUFFIX__", view["eyebrow"])
        .replace("__HEADLINE__", view["headline"])
        .replace("__YAXIS__", view["yaxis"])
    )

    out_html = OUTPUT_DIR / f"{view['stem']}.html"
    out_png = OUTPUT_DIR / f"{view['stem']}.png"
    out_html.write_text(html, encoding="utf-8")

    print(f"Saved: {out_html}")
    print(f"  {view['n_label']}: {n:,}")
    print(f"  median: {median}分 ・ mean: {mean:.2f}分 ・ range: {sorted_mins[0]}–{sorted_mins[-1]}分")
    print(f"  {MAX_MIN}+ overflow: {overflow_count:,}")

    html_to_png(out_html, out_png, selector=".page")
    print(f"Saved: {out_png}")


def main() -> None:
    total_rooms = 0
    # Collapse rooms into one property per (title, address) building; keep every station.
    building_mins: dict[tuple[str, str], list[int]] = {}

    with INPUT_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_rooms += 1
            rec = json.loads(line)
            key = (rec.get("title", ""), rec.get("address", ""))
            if key not in building_mins:
                building_mins[key] = parse_walk_mins(rec)

    walkable = [mins for mins in building_mins.values() if mins]
    no_walk = len(building_mins) - len(walkable)
    nearest_minutes = [min(mins) for mins in walkable]
    every_minutes = [m for mins in walkable for m in mins]

    print(f"rooms read : {total_rooms:,}")
    print(f"properties : {len(building_mins):,}  (rooms collapsed by title+address)")
    print(f"  with walk: {len(walkable):,}  (dropped bus/other-only: {no_walk:,})\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    render_view(VIEWS["nearest"], nearest_minutes)
    print()
    render_view(VIEWS["every"], every_minutes)

    htmls = [str(OUTPUT_DIR / f"{v['stem']}.html") for v in VIEWS.values()]
    subprocess.run(["open", "-a", "Google Chrome", *htmls], check=True)


if __name__ == "__main__":
    main()
