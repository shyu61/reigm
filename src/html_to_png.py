"""Render an HTML file (or string) to a PNG via headless Chromium (Playwright).

Used by exp scripts that generate dark-theme D3 visualizations and want a
shareable PNG (e.g. for notes / articles) in addition to the live HTML.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 900
DEFAULT_DEVICE_SCALE = 2  # 2x for retina-quality output
DEFAULT_WAIT_MS = 600  # buffer after networkidle for webfont swap / async draws


def html_to_png(
    html: str | Path,
    output_path: str | Path,
    *,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    device_scale_factor: int = DEFAULT_DEVICE_SCALE,
    full_page: bool = True,
    wait_ms: int = DEFAULT_WAIT_MS,
    selector: str | None = None,
) -> Path:
    """Render `html` (a path or raw HTML string) to a PNG at `output_path`.

    If `selector` is set, capture only that element's bounding box (trims away
    body padding / viewport whitespace). Otherwise capture the page per
    `full_page`. Returns the absolute output path.
    """
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(html, Path) or (isinstance(html, str) and Path(html).is_file()):
        url = Path(html).resolve().as_uri()
        html_content: str | None = None
    else:
        url = None
        html_content = html  # type: ignore[assignment]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                device_scale_factor=device_scale_factor,
            )
            page = ctx.new_page()
            if url is not None:
                page.goto(url, wait_until="networkidle")
            else:
                page.set_content(html_content or "", wait_until="networkidle")
            # Make sure webfonts that arrived via @import/<link> are applied.
            page.evaluate("document.fonts && document.fonts.ready")
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)
            if selector is not None:
                page.locator(selector).screenshot(path=str(output), omit_background=False)
            else:
                page.screenshot(path=str(output), full_page=full_page, omit_background=False)
        finally:
            browser.close()
    return output
