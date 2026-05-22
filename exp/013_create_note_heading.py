"""Compose the note article's heading image: short title over the cityscape.

The clean source photo (data/input/heading_001_base.png) gets a darkening scrim
and a punchy two-line title derived from the article H1, in the same visual
language as the X post cards (Noto Sans JP, yellow #ffe14d highlight). The final
PNG overwrites articles/note/heading.png at the standard note 1280x670 ratio.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from html_to_png import html_to_png

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / SCRIPT_PATH.stem  # intermediate HTML

BASE_PHOTO = PROJECT_ROOT / "data" / "input" / "heading_001_base.png"
HEADING_PNG = PROJECT_ROOT / "articles" / "note" / "heading.png"

# note's recommended heading ratio (1280x670 ~= 1.91:1).
CARD_WIDTH = 1280
CARD_HEIGHT = 670

PAGE_TEMPLATE = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@500;700;900&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --ink: #0e1116;
        --mark: #ffe14d;
      }
      * { box-sizing: border-box; }
      html, body {
        margin: 0;
        padding: 0;
        background: #ffffff;
        font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", system-ui, sans-serif;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
      }
      .card {
        position: relative;
        width: __WIDTH__px;
        height: __HEIGHT__px;
        overflow: hidden;
        color: #fff;
      }
      .photo {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      /* darkening scrim: heaviest at bottom-left where the title sits */
      .scrim {
        position: absolute;
        inset: 0;
        background:
          linear-gradient(105deg, rgba(8, 12, 18, 0.74) 0%, rgba(8, 12, 18, 0.30) 48%, rgba(8, 12, 18, 0.06) 78%),
          linear-gradient(0deg, rgba(8, 12, 18, 0.66) 0%, rgba(8, 12, 18, 0.10) 42%, rgba(8, 12, 18, 0.00) 70%);
      }
      .content {
        position: absolute;
        left: 72px;
        right: 72px;
        bottom: 64px;
      }
      .eyebrow {
        display: inline-block;
        font-size: 26px;
        font-weight: 700;
        letter-spacing: 0.06em;
        padding: 7px 16px;
        margin: 0 0 22px;
        border: 2px solid rgba(255, 255, 255, 0.9);
        border-radius: 999px;
        backdrop-filter: blur(2px);
      }
      .headline {
        font-size: 86px;
        font-weight: 900;
        line-height: 1.16;
        letter-spacing: 0.01em;
        margin: 0;
        text-shadow: 0 3px 22px rgba(0, 0, 0, 0.55);
      }
      .headline .accent { color: var(--mark); }
    </style>
  </head>
  <body>
    <div class="card">
      <img class="photo" src="__PHOTO__" alt="" />
      <div class="scrim"></div>
      <div class="content">
        <p class="eyebrow">東京23区 賃貸マンション 約3.8万件を大調査</p>
        <h1 class="headline">賃貸マンション名の<br><span class="accent">カタカナ語</span>ランキング</h1>
      </div>
    </div>
  </body>
</html>
"""


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    html = (
        PAGE_TEMPLATE.replace("__PHOTO__", data_uri(BASE_PHOTO))
        .replace("__WIDTH__", str(CARD_WIDTH))
        .replace("__HEIGHT__", str(CARD_HEIGHT))
    )
    html_path = OUTPUT_DIR / "heading.html"
    html_path.write_text(html, encoding="utf-8")

    html_to_png(html_path, HEADING_PNG, selector=".card")
    print(f"Saved: {HEADING_PNG}")


if __name__ == "__main__":
    main()
