"""Render an SNS-ready infographic of property-name token frequencies.

Reads `token_counts.csv` produced by 003 and emits a portrait HTML canvas
(1080×1350, Instagram 4:5) styled as a quiet editorial archive — warm paper,
mincho display type, hairline ledger rules, italic Garamond index figures.
Two stacked panels contrast 形態語 (functional building-category words)
against 装飾語 (decorative naming words).

Capture for SNS:
  chromium --headless --window-size=1080,1350 --screenshot=out.png \\
      --hide-scrollbars --default-background-color=00000000 \\
      file://$(pwd)/data/005_visualize_property_name_words/property_name_words.html
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
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@400;500;600;700&family=Noto+Serif+JP:wght@400;500;600;700&display=swap');

:root {
    --paper: #F0E8D5;
    --ink: #1B1E26;
    --subink: #5A5547;
    --muted: #ACA391;
    --hairline: #D6CBB3;
    --rule: #C8BC9E;
    --type: #344B5C;
    --style: #B05A3C;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
    background: #2A2722;
    font-family: "Inter", "Hiragino Sans", "Helvetica Neue", sans-serif;
    font-feature-settings: "palt" 1, "tnum" 1;
    -webkit-font-smoothing: antialiased;
    color: var(--ink);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
}

.canvas {
    width: 1080px;
    height: 1350px;
    background: var(--paper);
    position: relative;
    padding: 60px 72px 52px;
    display: flex;
    flex-direction: column;
    box-shadow: 0 30px 80px -30px rgba(0, 0, 0, 0.5);
    background-image:
        radial-gradient(ellipse at top left, rgba(255, 255, 255, 0.45) 0%, transparent 60%),
        radial-gradient(ellipse at bottom right, rgba(0, 0, 0, 0.03) 0%, transparent 55%);
}

.col-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 9.5px;
    letter-spacing: 0.36em;
    text-transform: uppercase;
    color: var(--subink);
    font-weight: 600;
    margin-bottom: 24px;
}
.col-top .mark {
    font-family: "Cormorant Garamond", serif;
    font-style: italic;
    font-weight: 500;
    font-size: 13px;
    letter-spacing: 0.05em;
    text-transform: none;
    color: var(--style);
}

.title {
    font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
    font-weight: 600;
    font-size: 44px;
    line-height: 1.08;
    letter-spacing: -0.005em;
    margin-bottom: 12px;
}
.title .em {
    color: var(--style);
}

.lede {
    font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
    font-weight: 400;
    font-size: 12.5px;
    line-height: 1.7;
    color: var(--subink);
    max-width: 720px;
    margin-bottom: 22px;
}

.kpis {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    column-gap: 24px;
    padding: 14px 0 12px;
    border-top: 1px solid var(--hairline);
    border-bottom: 1px solid var(--hairline);
}
.kpi { display: flex; flex-direction: column; }
.kpi-value {
    font-family: "Cormorant Garamond", "Georgia", serif;
    font-weight: 500;
    font-size: 30px;
    line-height: 1;
    letter-spacing: -0.005em;
    font-feature-settings: "tnum" 1, "lnum" 1;
}
.kpi-value .pct {
    font-size: 18px;
    font-style: italic;
    color: var(--subink);
    margin-left: 1px;
}
.kpi-label {
    font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
    font-size: 10.5px;
    color: var(--subink);
    margin-top: 8px;
    letter-spacing: 0.04em;
}

.panels {
    display: flex;
    flex-direction: column;
    gap: 22px;
    margin-top: 22px;
    flex: 1;
}

.panel { display: flex; flex-direction: column; }

.panel-head {
    display: grid;
    grid-template-columns: 48px 1fr;
    column-gap: 14px;
    align-items: baseline;
    margin-bottom: 10px;
}
.panel-num {
    font-family: "Cormorant Garamond", serif;
    font-style: italic;
    font-weight: 500;
    font-size: 30px;
    line-height: 1;
    letter-spacing: -0.01em;
}
.panel-num.type { color: var(--type); }
.panel-num.style { color: var(--style); }

.panel-titles { display: flex; flex-direction: column; }
.panel-eyebrow {
    font-size: 9.5px;
    letter-spacing: 0.32em;
    text-transform: uppercase;
    font-weight: 700;
    margin-bottom: 4px;
}
.panel-eyebrow.type { color: var(--type); }
.panel-eyebrow.style { color: var(--style); }
.panel-title {
    font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
    font-weight: 600;
    font-size: 17px;
    line-height: 1.25;
}
.panel-blurb {
    font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
    font-size: 10.5px;
    color: var(--subink);
    margin-top: 2px;
}

.rows { display: flex; flex-direction: column; }
.row {
    display: grid;
    grid-template-columns: 44px 130px 1fr 70px;
    align-items: center;
    column-gap: 16px;
    height: 24px;
    border-top: 1px solid var(--hairline);
}
.row:last-child { border-bottom: 1px solid var(--hairline); }

.idx {
    font-family: "Cormorant Garamond", serif;
    font-style: italic;
    font-weight: 500;
    font-size: 12px;
    line-height: 1;
    color: var(--muted);
    font-feature-settings: "tnum" 1, "lnum" 1;
    letter-spacing: 0.02em;
}

.token {
    font-family: "Noto Serif JP", "Hiragino Mincho ProN", serif;
    font-weight: 500;
    font-size: 13.5px;
    line-height: 1;
    text-align: right;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: 0.01em;
}

.bar-track {
    position: relative;
    height: 12px;
    display: flex;
    align-items: center;
}
.bar-track::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: 50%%;
    height: 1px;
    background: var(--rule);
}
.bar {
    position: relative;
    height: 4px;
    min-width: 2px;
    border-radius: 0;
}
.bar.type { background: var(--type); }
.bar.style { background: var(--style); }
.bar::after {
    content: "";
    position: absolute;
    right: -1px;
    top: -3px;
    width: 1px;
    height: 10px;
    background: currentColor;
    opacity: 0;
}

.count {
    font-family: "Cormorant Garamond", serif;
    font-weight: 500;
    font-size: 15px;
    line-height: 1;
    text-align: right;
    font-feature-settings: "tnum" 1, "lnum" 1;
    letter-spacing: 0.01em;
}
.count.type { color: var(--type); }
.count.style { color: var(--style); }

.colophon-bottom {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 18px;
    padding-top: 12px;
    border-top: 1px solid var(--hairline);
    font-size: 9px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--muted);
}
.colophon-bottom .seal {
    font-family: "Cormorant Garamond", serif;
    font-style: italic;
    font-weight: 500;
    font-size: 11px;
    letter-spacing: 0.04em;
    text-transform: none;
    color: var(--subink);
}
"""


def _row(idx: int, token: str, count: int, max_count: int, kind: str) -> str:
    pct = count / max_count * 100
    return (
        '<div class="row">'
        f'<span class="idx">№ {idx:03d}</span>'
        f'<span class="token">{escape(token)}</span>'
        '<span class="bar-track">'
        f'<span class="bar {kind}" style="width: {pct:.2f}%"></span>'
        "</span>"
        f'<span class="count {kind}">{count:,}</span>'
        "</div>"
    )


def _panel(numeral: str, eyebrow: str, title: str, blurb: str, rows_html: str, kind: str) -> str:
    return (
        '<section class="panel">'
        '<div class="panel-head">'
        f'<div class="panel-num {kind}">{escape(numeral)}</div>'
        '<div class="panel-titles">'
        f'<div class="panel-eyebrow {kind}">{escape(eyebrow)}</div>'
        f'<h2 class="panel-title">{escape(title)}</h2>'
        f'<p class="panel-blurb">{escape(blurb)}</p>'
        "</div>"
        "</div>"
        f'<div class="rows">{rows_html}</div>'
        "</section>"
    )


def _kpi(value: str, suffix: str, label: str) -> str:
    suffix_html = f'<span class="pct">{escape(suffix)}</span>' if suffix else ""
    return (
        '<div class="kpi">'
        f'<div class="kpi-value">{escape(value)}{suffix_html}</div>'
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

    type_rows = "".join(
        _row(i + 1, t, c, bar_max, "type")
        for i, (t, c) in enumerate(zip(type_df["token"], type_df["count"], strict=True))
    )
    style_rows = "".join(
        _row(i + 1, t, c, bar_max, "style")
        for i, (t, c) in enumerate(zip(style_df["token"], style_df["count"], strict=True))
    )

    kpis_html = "".join(
        [
            _kpi(f"{total:,}", "", "述べトークン総数"),
            _kpi(f"{type_total / total * 100:.1f}", "%", "形態語 シェア"),
            _kpi(f"{style_total / total * 100:.1f}", "%", "装飾語 シェア"),
            _kpi(f"{other_total / total * 100:.1f}", "%", "ブランド・その他"),
        ]
    )

    panels_html = _panel(
        "I.",
        "Category 01 · 形態語 / Functional",
        "物件タイプを示す語",
        f"建物そのものを示す機能語({TYPE_TOP_N}語すべて)",
        type_rows,
        "type",
    ) + _panel(
        "II.",
        "Category 02 · 装飾語 / Decorative",
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
<article class="canvas">
  <div class="col-top">
    <span>Tokyo Property-Name Lexicon · Vol. 001</span>
    <span class="mark">№ 005 — 2026</span>
  </div>
  <h1 class="title">東京の物件名を<br>つくる<span class="em">言葉</span>。</h1>
  <p class="lede">SUUMO 掲載タイトルから抽出したカタカナ語を、建物そのものを指す「形態語」と、
  印象を彩る「装飾語」に分けて出現回数順に並べた、静かな索引。</p>
  <div class="kpis">{kpis_html}</div>
  <div class="panels">{panels_html}</div>
  <div class="colophon-bottom">
    <span>Source · SUUMO 物件タイトル / Lexicon-based longest-match segmentation</span>
    <span class="seal">reigm — exp / 003 · 005</span>
  </div>
</article>
</body>
</html>
"""

    out = OUTPUT_DIR / "property_name_words.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote: {out}")


if __name__ == "__main__":
    main()
