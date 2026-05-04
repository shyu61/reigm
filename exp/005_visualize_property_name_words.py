"""Render an HTML infographic of property-name token frequencies.

Reads `token_counts.csv` produced by 003 and emits a single self-contained
HTML file styled for editorial / infographic-media use. Two-panel layout
contrasts:

  - 物件タイプ (形態語): functional building-category words.
  - 命名スタイル (装飾語): decorative naming words.
"""

from html import escape
from pathlib import Path

import polars as pl

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
INPUT_PATH = DATA_DIR / "003_analyze_property_name_words" / "token_counts.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem

TYPE_TOP_N = 13
STYLE_TOP_N = 15

CSS = """
:root {
    --bg: #FBF6EE;
    --ink: #1D1D1B;
    --subink: #6A655E;
    --muted: #9C958A;
    --rule: #E2D9CB;
    --type: #264653;
    --style: #E07856;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    background: var(--bg);
    color: var(--ink);
    font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Helvetica Neue",
                 "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
    font-feature-settings: "palt" 1;
    -webkit-font-smoothing: antialiased;
    font-size: 14px;
    line-height: 1.55;
}
.page {
    max-width: 1240px;
    margin: 0 auto;
    padding: 56px 64px 40px;
}
.eyebrow {
    font-size: 10.5px;
    letter-spacing: 0.32em;
    color: var(--style);
    font-weight: 700;
    text-transform: uppercase;
    margin-bottom: 12px;
}
h1.title {
    margin: 0 0 10px;
    font-size: 34px;
    font-weight: 800;
    letter-spacing: -0.01em;
}
.lede {
    margin: 0;
    color: var(--subink);
    font-size: 13.5px;
    max-width: 760px;
}
.kpis {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 32px;
    margin-top: 32px;
    padding: 22px 0 22px;
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
}
.kpi-value {
    font-size: 28px;
    font-weight: 800;
    line-height: 1.1;
    letter-spacing: -0.01em;
}
.kpi-label {
    font-size: 11px;
    color: var(--subink);
    margin-top: 6px;
    letter-spacing: 0.04em;
}
.panels {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 64px;
    margin-top: 36px;
}
.panel-eyebrow {
    font-size: 10.5px;
    letter-spacing: 0.18em;
    font-weight: 700;
    text-transform: uppercase;
}
.panel-eyebrow.type { color: var(--type); }
.panel-eyebrow.style { color: var(--style); }
h2.panel-title {
    margin: 6px 0 4px;
    font-size: 21px;
    font-weight: 800;
    letter-spacing: -0.005em;
}
.panel-blurb {
    margin: 0 0 22px;
    color: var(--subink);
    font-size: 12px;
}
.rows { display: flex; flex-direction: column; gap: 4px; }
.row {
    display: grid;
    grid-template-columns: 96px 1fr 60px;
    align-items: center;
    column-gap: 14px;
    padding: 5px 0;
}
.token {
    font-size: 13px;
    text-align: right;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.bar-track {
    position: relative;
    height: 18px;
    display: flex;
    align-items: center;
}
.bar-track::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: 50%;
    height: 1px;
    background: var(--rule);
}
.bar {
    position: relative;
    height: 100%;
    border-radius: 1px;
}
.bar.type { background: var(--type); }
.bar.style { background: var(--style); }
.count {
    font-size: 12px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    text-align: left;
}
.count.type { color: var(--type); }
.count.style { color: var(--style); }
footer {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 40px;
    padding-top: 18px;
    border-top: 1px solid var(--rule);
    color: var(--muted);
    font-size: 11px;
    font-family: "SF Mono", "Menlo", monospace;
}
"""


def _row(token: str, count: int, max_count: int, kind: str) -> str:
    pct = count / max_count * 100
    return (
        '<div class="row">'
        f'<span class="token">{escape(token)}</span>'
        f'<span class="bar-track"><span class="bar {kind}" style="width: {pct:.2f}%"></span></span>'
        f'<span class="count {kind}">{count:,}</span>'
        "</div>"
    )


def _panel(eyebrow: str, title: str, blurb: str, rows_html: str, kind: str) -> str:
    return (
        '<section class="panel">'
        f'<div class="panel-eyebrow {kind}">{escape(eyebrow)}</div>'
        f'<h2 class="panel-title">{escape(title)}</h2>'
        f'<p class="panel-blurb">{escape(blurb)}</p>'
        f'<div class="rows">{rows_html}</div>'
        "</section>"
    )


def _kpi(value: str, label: str) -> str:
    return (
        '<div class="kpi">'
        f'<div class="kpi-value">{escape(value)}</div>'
        f'<div class="kpi-label">{escape(label)}</div>'
        "</div>"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pl.read_csv(INPUT_PATH)
    type_df = df.filter(pl.col("category") == "type").sort("count", descending=True).head(TYPE_TOP_N)
    style_df = df.filter(pl.col("category") == "style").sort("count", descending=True).head(STYLE_TOP_N)

    type_total = int(df.filter(pl.col("category") == "type")["count"].sum())
    style_total = int(df.filter(pl.col("category") == "style")["count"].sum())
    other_total = int(df.filter(pl.col("category").is_null())["count"].sum())
    total = type_total + style_total + other_total

    bar_max = max(int(type_df["count"].max()), int(style_df["count"].max()))

    type_rows = "".join(_row(t, c, bar_max, "type") for t, c in zip(type_df["token"], type_df["count"], strict=True))
    style_rows = "".join(
        _row(t, c, bar_max, "style") for t, c in zip(style_df["token"], style_df["count"], strict=True)
    )

    kpis_html = "".join(
        [
            _kpi(f"{total:,}", "分析対象トークン (述べ)"),
            _kpi(f"{type_total / total * 100:.1f}%", "形態語 シェア"),
            _kpi(f"{style_total / total * 100:.1f}%", "装飾語 シェア"),
            _kpi(f"{other_total / total * 100:.1f}%", "ブランド・その他"),
        ]
    )

    panels_html = _panel(
        "Category 01 — 形態語",
        "物件タイプを示す語",
        f"建物そのものを示す機能語({TYPE_TOP_N}語すべて)",
        type_rows,
        "type",
    ) + _panel(
        "Category 02 — 装飾語",
        "命名スタイルを彩る語",
        f"印象や立地ニュアンスを添える語(top {STYLE_TOP_N})",
        style_rows,
        "style",
    )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>東京の物件名をつくる言葉</title>
<style>{CSS}</style>
</head>
<body>
<main class="page">
<div class="eyebrow">Tokyo Property-Name Lexicon</div>
<h1 class="title">東京の物件名をつくる言葉</h1>
<p class="lede">SUUMO 掲載タイトルから抽出したカタカナ語を「形態語」と「装飾語」に分類し、出現回数で並べた。</p>
<div class="kpis">{kpis_html}</div>
<div class="panels">{panels_html}</div>
<footer>
<span>Source: SUUMO 掲載物件タイトル · Lexicon-based longest-match segmentation</span>
<span>exp/003_analyze_property_name_words.py</span>
</footer>
</main>
</body>
</html>
"""

    out = OUTPUT_DIR / "property_name_words.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote: {out}")


if __name__ == "__main__":
    main()
