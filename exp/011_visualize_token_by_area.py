"""Render 009's per-token × ward lift as choropleth small-multiples over Tokyo 23-ku.

For each chosen token we draw a Tokyo 23-ku map filled by the token's lift in
that ward (>1 = over-represented, <1 = under-represented). Empty wards (no
listings with the token) render as the page background so they read as "absent"
rather than "below baseline".

Inputs:
  - data/009_aggregate_token_by_area/token_ward_long.csv

Outputs:
  - data/011_visualize_token_by_area/cache/tokyo_23ku.geojson  (cached boundary file)
  - data/011_visualize_token_by_area/index.html                (rendered page)
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

import click
import polars as pl

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
INPUT_CSV = PROJECT_ROOT / "data" / "009_aggregate_token_by_area" / "token_ward_long.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem
CACHE_DIR = OUTPUT_DIR / "cache"
GEOJSON_CACHE = CACHE_DIR / "tokyo_23ku.geojson"
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_PNG = OUTPUT_DIR / "index.png"

# Per-ward GeoJSON from niiyz/JapanCityGeoJson (high-res; 23 individual files
# at JIS codes 13101..13123 merged into one FeatureCollection).
WARD_GEO_URL_TMPL = "https://raw.githubusercontent.com/niiyz/JapanCityGeoJson/master/geojson/13/{code}.json"
WARD_JIS_CODES = tuple(str(c) for c in range(13101, 13124))
WARD_NAME_PROP = "N03_004"

DEFAULT_TOKENS = ("フォレスト", "ヒルズ", "スカイ", "タワー", "ベイ", "リバー")

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <title>物件名トークン × エリア (東京23区)</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #eaf3fa;
        --panel: #ffffff;
        --ink: #0e1116;
        --muted: #5c6470;
        --border: #cbd5dc;
      }
      * { box-sizing: border-box; }
      html, body {
        margin: 0;
        padding: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: "Inter", "Hiragino Sans", "Yu Gothic UI", system-ui, sans-serif;
        -webkit-font-smoothing: antialiased;
      }
      .page {
        max-width: 1280px;
        margin: 0 auto;
        padding: 56px 32px 96px;
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 18px;
      }
      @media (max-width: 900px) { .grid { grid-template-columns: repeat(2, 1fr); } }
      @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
      .card {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 14px 14px 10px;
        position: relative;
      }
      .card h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 700;
        letter-spacing: -0.01em;
      }
      .card .meta {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11px;
        color: var(--muted);
        margin-top: 2px;
        margin-bottom: 8px;
      }
      .map svg { width: 100%; height: auto; display: block; }
      .ward { stroke: rgba(14,17,22,0.25); stroke-width: 0.6; }
      .ward.empty { fill: var(--bg); }
      .ward-label {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-weight: 700;
        fill: #0e1116;
        paint-order: stroke;
        stroke: rgba(255,255,255,0.85);
        stroke-width: 2.4px;
        stroke-linejoin: round;
        pointer-events: none;
      }
      .ward-label .name { font-size: 9px; font-weight: 600; }
      .ward-label .lift { font-size: 11px; font-weight: 800; }
      .legend {
        margin-top: 40px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .legend .label {
        font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.08em;
        color: var(--ink);
        text-transform: uppercase;
      }
      .legend svg { display: block; }
    </style>
  </head>
  <body>
    <div class="page">
      <div id="grid" class="grid"></div>

      <div class="legend">
        <div class="label">LIFT (vs. ward base rate)</div>
        <svg id="legend-svg" width="360" height="34"></svg>
      </div>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
      const GEO = __GEO_JSON__;
      const DATA = __DATA_JSON__;  // {token: {ward: {count, lift}}, ...}
      const TOKEN_META = __META_JSON__; // {token: {n: total}}
      const TOKENS = __TOKENS_JSON__;
      const LIFT_DOMAIN = __LIFT_DOMAIN__;  // [min, max] across selected tokens
      const WARD_NAME_PROP = "__WARD_NAME_PROP__";

      const features = GEO.features;

      // Shared color scale on a light background: pale for low lift, salmon
      // saturated for high lift.
      const COLOR_LO = "#f4ece6";
      const COLOR_MID = "#e9b89e";
      const COLOR_HI = "#c45a3a";
      const color = d3
        .scaleLinear()
        .domain([
          LIFT_DOMAIN[0],
          1,
          LIFT_DOMAIN[1],
        ])
        .range([COLOR_LO, COLOR_MID, COLOR_HI])
        .clamp(true);

      // Shared projection fitted to the union of 23-ku bounds.
      const W = 360;
      const H = 280;
      const sharedProjection = d3
        .geoMercator()
        .fitSize([W - 12, H - 12], { type: "FeatureCollection", features });
      const sharedPath = d3.geoPath(sharedProjection);

      const fmt = d3.format(".2f");

      const grid = d3.select("#grid");
      TOKENS.forEach((token) => {
        const card = grid.append("div").attr("class", "card");
        const meta = TOKEN_META[token] || { n: 0 };
        card.append("h2").text(token);
        card
          .append("div")
          .attr("class", "meta")
          .text(`n=${meta.n.toLocaleString()}`);

        const svg = card
          .append("div")
          .attr("class", "map")
          .append("svg")
          .attr("viewBox", `0 0 ${W} ${H}`);

        const tokenData = DATA[token] || {};
        svg
          .selectAll("path.ward")
          .data(features)
          .join("path")
          .attr("class", (d) => {
            const wd = tokenData[d.properties[WARD_NAME_PROP]];
            return wd ? "ward" : "ward empty";
          })
          .attr("d", sharedPath)
          .attr("fill", (d) => {
            const wd = tokenData[d.properties[WARD_NAME_PROP]];
            return wd ? color(wd.lift) : null;
          });

        // Annotate the most over-represented wards (lift >= LABEL_LIFT_MIN,
        // plus a top-N floor so every map gets a few labels even when nothing
        // crosses the threshold).
        const LABEL_LIFT_MIN = 1.5;
        const LABEL_TOP_N = 3;
        const ranked = features
          .map((f) => {
            const wd = tokenData[f.properties[WARD_NAME_PROP]];
            return wd ? { feature: f, ward: f.properties[WARD_NAME_PROP], lift: wd.lift } : null;
          })
          .filter(Boolean)
          .sort((a, b) => b.lift - a.lift);
        const labelSet = new Set(
          ranked
            .filter((r, i) => i < LABEL_TOP_N || r.lift >= LABEL_LIFT_MIN)
            .map((r) => r.ward),
        );
        // Manual nudges (viewBox units) for wards whose centroids sit so close
        // that their two-line labels collide (e.g. 千代田区 / 中央区).
        const LABEL_OFFSETS = {
          "千代田区": [0, -8],
          "中央区": [0, 6],
          "江東区": [8, 2],
        };
        const labels = svg
          .selectAll("g.ward-label")
          .data(ranked.filter((r) => labelSet.has(r.ward)))
          .join("g")
          .attr("class", "ward-label")
          .attr("transform", (d) => {
            const [cx, cy] = sharedPath.centroid(d.feature);
            const off = LABEL_OFFSETS[d.ward] || [0, 0];
            return `translate(${cx + off[0]}, ${cy + off[1]})`;
          });
        labels
          .append("text")
          .attr("class", "name")
          .attr("text-anchor", "middle")
          .attr("dominant-baseline", "central")
          .attr("dy", "-0.55em")
          .text((d) => d.ward);
        labels
          .append("text")
          .attr("class", "lift")
          .attr("text-anchor", "middle")
          .attr("dominant-baseline", "central")
          .attr("dy", "0.55em")
          .text((d) => `×${fmt(d.lift)}`);
      });

      // --- legend gradient ---
      const lgW = 360;
      const lgH = 14;
      const legendSvg = d3.select("#legend-svg");
      const defs = legendSvg.append("defs");
      const grad = defs
        .append("linearGradient")
        .attr("id", "legendGrad")
        .attr("x1", "0%")
        .attr("x2", "100%");
      const stops = 20;
      const liftLo = LIFT_DOMAIN[0];
      const liftHi = LIFT_DOMAIN[1];
      for (let i = 0; i <= stops; i++) {
        const t = i / stops;
        const lift = liftLo + (liftHi - liftLo) * t;
        grad
          .append("stop")
          .attr("offset", (t * 100) + "%")
          .attr("stop-color", color(lift));
      }
      legendSvg
        .append("rect")
        .attr("x", 0)
        .attr("y", 4)
        .attr("width", lgW)
        .attr("height", lgH)
        .attr("rx", 3)
        .attr("fill", "url(#legendGrad)");
      // ticks at 1.0 and hi. The hi tick is end-anchored so its label stays
      // inside the SVG (middle anchor at x=lgW clips half off).
      const ticks = [1, liftHi];
      const xScale = d3.scaleLinear().domain([liftLo, liftHi]).range([0, lgW]);
      ticks.forEach((t, i) => {
        const isLast = i === ticks.length - 1;
        legendSvg
          .append("text")
          .attr("x", xScale(t))
          .attr("y", lgH + 18)
          .attr("text-anchor", isLast ? "end" : "middle")
          .attr("fill", "#0e1116")
          .style("font-family", "JetBrains Mono, ui-monospace, monospace")
          .style("font-size", "11px")
          .style("font-weight", 600)
          .text(isLast ? Math.round(t).toString() : t.toFixed(2));
      });
    </script>
  </body>
</html>
"""


def _load_geojson() -> dict:
    """Merge the 23 per-ward GeoJSON files into one FeatureCollection (cached)."""
    if GEOJSON_CACHE.exists():
        return json.loads(GEOJSON_CACHE.read_text(encoding="utf-8"))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    features: list[dict] = []
    for code in WARD_JIS_CODES:
        url = WARD_GEO_URL_TMPL.format(code=code)
        print(f"fetching {url}")
        with urllib.request.urlopen(url) as resp:
            ward_geo = json.loads(resp.read().decode("utf-8"))
        features.extend(ward_geo["features"])
    merged = {"type": "FeatureCollection", "features": features}
    GEOJSON_CACHE.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return merged


def _ward_names(geo: dict) -> set[str]:
    return {f["properties"][WARD_NAME_PROP] for f in geo["features"]}


@click.command()
@click.option(
    "--tokens",
    default=",".join(DEFAULT_TOKENS),
    show_default=True,
    help="Comma-separated tokens to render (one map per token).",
)
def main(tokens: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    geo = _load_geojson()
    valid_wards = _ward_names(geo)
    print(f"23-ku boundaries: {len(valid_wards)} wards")

    token_list = [t.strip() for t in tokens.split(",") if t.strip()]
    if not token_list:
        raise click.UsageError("--tokens must contain at least one token")

    df = pl.read_csv(INPUT_CSV)
    df = df.filter(pl.col("token").is_in(token_list)).filter(pl.col("ward").is_in(list(valid_wards)))
    missing = [t for t in token_list if t not in set(df["token"].unique().to_list())]
    if missing:
        print(f"warning: no rows for tokens {missing}; they will render as all-empty")

    data: dict[str, dict[str, dict[str, float]]] = {t: {} for t in token_list}
    meta: dict[str, dict[str, int]] = {}
    for row in df.iter_rows(named=True):
        data[row["token"]][row["ward"]] = {
            "count": int(row["count"]),
            "lift": float(row["lift"]),
        }
    for tok in token_list:
        meta[tok] = {"n": sum(v["count"] for v in data[tok].values())}

    all_lifts = [v["lift"] for tok in token_list for v in data[tok].values()]
    if not all_lifts:
        raise click.UsageError("No lift values found for the requested tokens.")
    lift_lo = min(all_lifts)
    lift_hi = max(all_lifts)
    # Symmetric padding so 1.0 sits sensibly inside the domain.
    lift_lo = min(lift_lo, 0.5)
    lift_hi = max(lift_hi, 1.5)
    print(f"lift domain across tokens: [{lift_lo:.2f}, {lift_hi:.2f}]")

    html = (
        HTML_TEMPLATE.replace("__GEO_JSON__", json.dumps(geo, ensure_ascii=False))
        .replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
        .replace("__META_JSON__", json.dumps(meta, ensure_ascii=False))
        .replace("__TOKENS_JSON__", json.dumps(token_list, ensure_ascii=False))
        .replace("__LIFT_DOMAIN__", json.dumps([lift_lo, lift_hi]))
        .replace("__WARD_NAME_PROP__", WARD_NAME_PROP)
    )
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_HTML}")

    html_to_png(OUTPUT_HTML, OUTPUT_PNG, selector=".page")
    print(f"Saved: {OUTPUT_PNG}")

    subprocess.run(["open", "-a", "Google Chrome", str(OUTPUT_HTML)], check=True)


if __name__ == "__main__":
    main()
