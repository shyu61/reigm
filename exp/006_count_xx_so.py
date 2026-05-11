"""Count distinct buildings whose name ends in 荘 (e.g., 山田荘, 第一荘).

Pipeline:
  1. Normalize titles (NFKC, strip parens prefix).
  2. Filter descriptive titles (e.g., 戸建, 共同住宅).
  3. Strip wing/unit suffixes (e.g., A棟, 第1号館) so 山田荘A棟 still counts.
  4. Dedupe by (name, address) so multiple rooms in one building count once.
"""

import json
import re
import unicodedata
from pathlib import Path

import click

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"

DESCRIPTIVE_TITLE_RE = re.compile(r"駅\s.*階建|築\d+年|戸建|貸家|借家|賃貸|貸マンション|共同住宅|倉庫|店舗|事務所")
PARENS_PREFIX_RE = re.compile(r"^\s*(?:[\(（][^\)）]*[\)）]|\*+)\s*")
WING_SUFFIX_RE = re.compile(
    r"(?:"
    r"[東西南北中央][棟館]"
    r"|第?[壱弐参一二三四五六七八九十拾0-9]+号[棟館]"
    r"|[壱弐参一二三四五六七八九十拾0-9]+番館"
    r"|(?<![A-Za-z])[A-Za-z][棟館]"
    r")$"
)
TAIL_SEP_CHARS = " 　・"


def _normalize_title(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = PARENS_PREFIX_RE.sub("", s)
    s = s.replace("　", " ").strip()
    return s


def _is_descriptive(s: str) -> bool:
    return bool(DESCRIPTIVE_TITLE_RE.search(s))


def _strip_wing_suffix(s: str) -> str:
    while True:
        prev = s
        s = WING_SUFFIX_RE.sub("", s).rstrip(TAIL_SEP_CHARS)
        if s == prev:
            return s


@click.command()
def main() -> None:
    all_buildings: set[tuple[str, str]] = set()
    so_buildings: set[tuple[str, str]] = set()
    with LISTINGS_PATH.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r.get("title")
            if not t:
                continue
            n = _normalize_title(t)
            if _is_descriptive(n):
                continue
            n = _strip_wing_suffix(n)
            key = (n, r.get("address", ""))
            all_buildings.add(key)
            if n.endswith("荘"):
                so_buildings.add(key)

    total = len(all_buildings)
    so = len(so_buildings)
    print(f"distinct buildings (named):   {total:,}")
    print(f"distinct 荘 buildings:        {so:,}  ({so / total:.2%})")


if __name__ == "__main__":
    main()
