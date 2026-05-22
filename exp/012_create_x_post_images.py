"""Compose X (Twitter) post images from the note article's section charts.

Each of the article's three sections gets one X post image: the source chart
(embedded as base64) sits under a styled "conclusion-first" caption with an
annotation that highlights the surprise point, per data/input/article_design.md
(X section). PNGs are written to articles/x/; intermediate HTML lands in data/.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem  # intermediate HTML
POST_DIR = PROJECT_ROOT / "articles" / "x" / "001_property_name_words"  # final PNGs

RANKING_PNG = PROJECT_ROOT / "data" / "014_visualize_token_counts_x" / "index.png"
ELEVATION_PNG = PROJECT_ROOT / "data" / "010_visualize_name_elevation" / "index.png"
TOWER_PNG = PROJECT_ROOT / "data" / "011_visualize_token_by_area" / "tower.png"

PAGE_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --bg: #e3eef6;
        --ink: #0e1116;
        --muted: #5c6470;
        --accent: #8fbed9;
        --hot: #e0533d;
        --mark: #ffe14d;
      }
      * { box-sizing: border-box; }
      html, body {
        margin: 0;
        padding: 0;
        background: #ffffff;
        font-family: "Inter", "Hiragino Sans", "Yu Gothic UI", system-ui, sans-serif;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
      }
      .card {
        width: __WIDTH__px;
        background: var(--bg);
        padding: 52px 56px 44px;
        color: var(--ink);
      }
      .eyebrow {
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: var(--accent);
        margin: 0 0 14px;
      }
      .headline {
        font-size: 50px;
        font-weight: 900;
        line-height: 1.28;
        letter-spacing: -0.01em;
        margin: 0;
      }
      .headline .mark {
        background: linear-gradient(transparent 58%, var(--mark) 58%);
        padding: 0 2px;
      }
      .headline .hot { color: var(--hot); }
      .chartwrap {
        position: relative;
        margin-top: 30px;
      }
      .chartwrap img {
        width: 100%;
        display: block;
      }
      /* speech-bubble callout with a downward tail */
      .callout {
        position: absolute;
        background: var(--hot);
        color: #fff;
        font-weight: 800;
        font-size: 26px;
        line-height: 1.32;
        padding: 12px 18px;
        border-radius: 14px;
        box-shadow: 0 10px 26px rgba(224, 83, 61, 0.32);
        text-align: center;
      }
      .callout.down::after {
        content: "";
        position: absolute;
        bottom: -14px;
        left: var(--tail, 50%);
        transform: translateX(-50%);
        border: 9px solid transparent;
        border-top-color: var(--hot);
      }
      .bignum {
        position: absolute;
        font-weight: 900;
        color: var(--hot);
        line-height: 0.9;
        text-shadow: 0 3px 0 #fff, 0 0 18px rgba(255,255,255,0.9);
      }
      .subnote {
        position: absolute;
        font-size: 24px;
        font-weight: 800;
        color: var(--ink);
      }
      .ring {
        position: absolute;
        border: 4px solid var(--hot);
        border-radius: 16px;
        box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.65);
      }
      .anno-label {
        position: absolute;
        font-size: 26px;
        font-weight: 800;
        color: var(--hot);
      }
      .chip {
        position: absolute;
        background: var(--hot);
        color: #fff;
        font-size: 26px;
        font-weight: 800;
        padding: 4px 16px;
        border-radius: 999px;
      }
      .footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 26px;
        font-size: 20px;
        font-weight: 600;
        color: var(--muted);
      }
      .footer .note {
        color: var(--ink);
        background: #fff;
        border: 2px solid var(--ink);
        border-radius: 999px;
        padding: 6px 18px;
      }
    </style>
  </head>
  <body>
    <div class="card">__INNER__</div>
  </body>
</html>
"""


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_page(inner: str, width: int) -> str:
    return PAGE_TEMPLATE.replace("__INNER__", inner).replace("__WIDTH__", str(width))


def post1_ranking() -> str:
    img = data_uri(RANKING_PNG)
    return f"""
      <p class="eyebrow">東京23区 賃貸マンション名 大調査</p>
      <h1 class="headline">一番多いカタカナ語は、<span class="mark">「ハイツ」</span>。<br>
        でも2位との差は、たった<span class="hot">15件</span>。</h1>
      <div class="chartwrap">
        <img src="{img}" alt="カタカナ語ランキングtop10" />
        <div class="ring" style="top:10%; left:84.5%; width:14.5%; height:22.5%;"></div>
        <div class="anno-label" style="top:1%; right:0.5%;">↓ 差はたった15件</div>
      </div>
      <div class="footer"><span>カタカナ語ランキング top10</span><span class="note">詳しくは note で →</span></div>
    """


def post2_elevation() -> str:
    img = data_uri(ELEVATION_PNG)
    return f"""
      <p class="eyebrow">賃貸マンション名 × 標高データ（国土地理院）</p>
      <h1 class="headline">ヒルズは、丘にあった。<br>
        でも<span class="hot">スカイ</span>は、空にいなかった。</h1>
      <div class="chartwrap">
        <img src="{img}" alt="カタカナ語 × 標高" />
        <div class="callout down" style="top:10%; left:33%; --tail:26%;">スカイなのに<br>低地に集中!?</div>
      </div>
      <div class="footer">
        <span>地形ワード × 平均標高（baseline 19.76m）</span>
        <span class="note">詳しくは note で →</span>
      </div>
    """


def post3_tower() -> str:
    img = data_uri(TOWER_PNG)
    return f"""
      <p class="eyebrow">「タワー」は本当に港区に多いのか？</p>
      <h1 class="headline">タワマンは、本当に<span class="mark">港区</span>だらけ。<br>
        出現率は23区平均の<span class="hot">7倍超</span>。</h1>
      <div class="chartwrap">
        <img src="{img}" alt="タワー × 23区の分布" />
        <div class="subnote" style="top:2.5%; right:3%; color:var(--muted);">港区の出現率は</div>
        <div class="bignum" style="top:6%; right:2.5%; font-size:104px;">×7.16</div>
        <div class="subnote" style="top:22%; right:3%;">23区平均の7倍超</div>
      </div>
      <div class="footer">
        <span>「タワー」出現率 × 23区（lift）</span>
        <span class="note">詳しくは note で →</span>
      </div>
    """


POSTS = [
    ("post1_ranking", 1240, post1_ranking),
    ("post2_elevation", 1120, post2_elevation),
    ("post3_tower", 1080, post3_tower),
]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    POST_DIR.mkdir(parents=True, exist_ok=True)

    for name, width, builder in POSTS:
        html = build_page(builder(), width)
        html_path = OUTPUT_DIR / f"{name}.html"
        html_path.write_text(html, encoding="utf-8")

        png_path = POST_DIR / f"{name}.png"
        html_to_png(html_path, png_path, selector=".card")
        print(f"Saved: {png_path}")


if __name__ == "__main__":
    main()
