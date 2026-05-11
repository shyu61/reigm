"""
Render an HTML page in a headless browser and extract a matching <svg> element
as a standalone .svg file. Useful for capturing D3 / JS-rendered charts.
"""

from __future__ import annotations

from pathlib import Path

import click
from playwright.sync_api import sync_playwright

SVG_SELECTOR = "svg"
RENDER_SETTLE_MS = 500

SVG_NAMESPACE = 'xmlns="http://www.w3.org/2000/svg"'
XLINK_NAMESPACE = 'xmlns:xlink="http://www.w3.org/1999/xlink"'

# Collect all CSS rules from the page (including @import-style cross-origin sheets
# like Google Fonts) so the extracted SVG can render standalone.
COLLECT_CSS_JS = """
() => {
  const parts = [];
  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules) parts.push(rule.cssText);
    } catch (e) {
      if (sheet.href) parts.push(`@import url(${JSON.stringify(sheet.href)});`);
    }
  }
  return parts.join('\\n');
}
"""


def ensure_namespaces(svg: str) -> str:
    if SVG_NAMESPACE not in svg:
        svg = svg.replace("<svg", f"<svg {SVG_NAMESPACE}", 1)
    if "xlink:" in svg and XLINK_NAMESPACE not in svg:
        svg = svg.replace("<svg", f"<svg {XLINK_NAMESPACE}", 1)
    return svg


def inject_styles(svg: str, css: str) -> str:
    if not css.strip():
        return svg
    style_block = f"<defs><style><![CDATA[\n{css}\n]]></style></defs>"
    end_of_open_tag = svg.find(">")
    if end_of_open_tag == -1:
        return svg
    return svg[: end_of_open_tag + 1] + style_block + svg[end_of_open_tag + 1 :]


def resolve_source(source: str) -> str:
    if source.startswith(("http://", "https://", "file://")):
        return source
    return Path(source).resolve().as_uri()


@click.command()
@click.option(
    "--input",
    "-i",
    "source",
    required=True,
    type=str,
    help="HTML file path or URL to render.",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the SVG. Defaults to <input>.svg next to the input file.",
)
@click.option(
    "--viewport-width",
    type=int,
    default=1280,
    show_default=True,
    help="Headless browser viewport width.",
)
@click.option(
    "--viewport-height",
    type=int,
    default=900,
    show_default=True,
    help="Headless browser viewport height.",
)
def main(
    source: str,
    output_path: Path | None,
    viewport_width: int,
    viewport_height: int,
) -> None:
    url = resolve_source(source)

    if output_path is None:
        if url.startswith("file://"):
            output_path = Path(url[len("file://") :]).with_suffix(".svg")
        else:
            output_path = Path.cwd() / "out.svg"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": viewport_width, "height": viewport_height})
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(SVG_SELECTOR, state="attached")
        page.wait_for_timeout(RENDER_SETTLE_MS)
        svg_html = page.eval_on_selector(SVG_SELECTOR, "el => el.outerHTML")
        css = page.evaluate(COLLECT_CSS_JS)
        browser.close()

    svg_html = inject_styles(ensure_namespaces(svg_html), css)
    output_path.write_text(svg_html, encoding="utf-8")
    print(f"Saved: {output_path} ({len(svg_html):,} bytes)")


if __name__ == "__main__":
    main()
