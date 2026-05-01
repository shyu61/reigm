"""Build a frequency distribution of sub-tokens used in property names.

Pipeline:
  1. Normalize titles (NFKC: 全角半角・記号・ローマ数字).
  2. Strip tails (place names from address dict).
  3. Extract katakana chunks and segment them via lexicon longest-match.
  4. Aggregate sub-token counts (e.g. ヒルズ, メゾン, レジデンス).

The lexicon (LEXICON) seeds known property-name affixes; chunks that don't
match anything stay as a single token (likely brand names). The CSV output
flags each token as in/out of lexicon so the lexicon can be grown iteratively.

Outputs:
  - Console: top-N tokens.
  - CSV: full token frequency distribution with in_lexicon flag.
  - CSV: sample of (raw → cleaned → segmented) for spot-checking.
"""

import csv
import json
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path

import click

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
LISTINGS_PATH = DATA_DIR / "001_fetch_suumo" / "listings.jsonl"
ADDRESS_DIR = DATA_DIR / "input" / "address_data"
STATIONS_PATH = DATA_DIR / "input" / "station_data" / "tokyo_23ku_stations.txt"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
CACHE_DIR = OUTPUT_DIR / "cache"

KATAKANA_RE = re.compile(r"[゠-ヿー]+")
DESCRIPTIVE_TITLE_RE = re.compile(r"駅\s.*階建|築\d+年|戸建|貸家|借家|賃貸|貸マンション|共同住宅|倉庫|店舗|事務所")
CHOME_RE = re.compile(r"[一二三四五六七八九十百0-9]+丁目$")
PARENS_PREFIX_RE = re.compile(r"^\s*(?:[\(（][^\)）]*[\)）]|\*+)\s*")
ROMAN_NUMERAL_RE = re.compile(r"(?<![A-Za-z])(?:VIII|VII|XII|XI|IX|VI|IV|III|II|X|V|I)$")
DIRECTION_WORD_RE = re.compile(
    r"(?<![A-Za-z])(?:NORTH|SOUTH|EAST|WEST|CENTRAL|CENTER|ノース|サウス|イースト|ウエスト|ウェスト|セントラル)$",
    re.IGNORECASE,
)
WING_SUFFIX_RE = re.compile(
    r"(?:"
    r"[東西南北中央][棟館]"
    r"|第?[壱弐参一二三四五六七八九十拾0-9]+号[棟館]"
    r"|[壱弐参一二三四五六七八九十拾0-9]+番館"
    r"|(?<![A-Za-z])[A-Za-z][棟館]"
    r")$"
)
TAIL_SEP_CHARS = " 　・"
TRAILING_DIGITS_RE = re.compile(r"^(.*?)\d+$")
MIN_CHUNK_LEN = 2
MIN_TOKEN_LEN = 2
TOP_N = 50

# Known property-name affixes. Add to this iteratively by reviewing the
# `in_lexicon=""` rows of the output CSV — high-frequency unclassified tokens
# are candidates for promotion to category words.
LEXICON: tuple[str, ...] = (
    # 接尾(住居系)
    "ハイツ",
    "ハウス",
    "レジデンス",
    "マンション",
    "アパートメント",
    "ホームズ",
    "コーポ",
    "メゾン",
    "カーサ",
    "カーザ",
    "シャトー",
    "パレス",
    "ヴィラ",
    "ヴィレッジ",
    "ビレッジ",
    "フラット",
    "スイート",
    "アネックス",
    "ロフト",
    # 接尾(地形・場所)
    "ヒルズ",
    "ヒル",
    "ガーデン",
    "パーク",
    "フォレスト",
    "テラス",
    "コート",
    "プレイス",
    "スクエア",
    "タワー",
    "タワーズ",
    "ベイ",
    "リバー",
    "シティ",
    "タウン",
    "プラザ",
    "フォルト",
    "フォート",
    "ポート",
    "ステージ",
    # 接頭(装飾・形容)
    "グランデ",
    "グラン",
    "プレミア",
    "プレミアム",
    "グレイス",
    "クレスト",
    "ロイヤル",
    "インペリアル",
    "ノーブル",
    "クラシック",
    "モダン",
    "ヌーヴォ",
    "ベラ",
    "ベル",
    "ビアン",
    "ボン",
    "ファースト",
    "プライム",
    "ウイング",
    "アーバン",
    "アーク",
    "エクセレント",
    "エスポワール",
    "レスポワール",
)
LEXICON_SET: frozenset[str] = frozenset(LEXICON)
LEXICON_SORTED: tuple[str, ...] = tuple(sorted(LEXICON_SET, key=len, reverse=True))
SEPARATOR_CHARS = "・"


def _cache_load(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _cache_save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --- Step 1: Normalize titles ---


def _normalize_title(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = PARENS_PREFIX_RE.sub("", s)
    s = s.replace("　", " ").strip()
    return s


def _is_descriptive(s: str) -> bool:
    return bool(DESCRIPTIVE_TITLE_RE.search(s))


def step1_normalize(raw_titles: list[str]) -> list[tuple[str, str]]:
    """Return (raw, normalized) pairs, filtering descriptive titles."""
    cache = CACHE_DIR / "step1_normalized.json"
    if (cached := _cache_load(cache)) is not None:
        out = [(x[0], x[1]) for x in cached]
        print(f"step1: loaded {len(out):,} from cache")
        return out
    out = []
    skipped = 0
    for t in raw_titles:
        n = _normalize_title(t)
        if _is_descriptive(n):
            skipped += 1
            continue
        out.append((t, n))
    print(f"step1: kept {len(out):,}, skipped descriptive {skipped:,}")
    _cache_save(cache, out)
    return out


# --- Step 2: Strip place-name / Roman-numeral / direction-word tails ---


def _add_with_kana_variants(places: set[str], s: str) -> None:
    """Add s plus its hiragana↔katakana variants (e.g., 四つ木 ↔ 四ツ木)."""
    if not s:
        return
    places.add(s)
    kata = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)
    if kata != s:
        places.add(kata)
    hira = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)
    if hira != s:
        places.add(hira)


def _load_place_dict(address_dir: Path, stations_path: Path) -> set[str]:
    """Build a set of place names from JIS address CSVs + Tokyo 23-ku station names."""
    places: set[str] = set()
    for csv_path in sorted(address_dir.glob("*.csv")):
        with csv_path.open(encoding="cp932", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ward = row.get("市区町村名", "").strip()
                if ward:
                    _add_with_kana_variants(places, ward)
                    for suffix in ("区", "市", "町", "村"):
                        if ward.endswith(suffix) and len(ward) > 1:
                            _add_with_kana_variants(places, ward[: -len(suffix)])
                area = row.get("大字町丁目名", "").strip()
                if area:
                    _add_with_kana_variants(places, area)
                    stem = CHOME_RE.sub("", area)
                    if stem:
                        _add_with_kana_variants(places, stem)
                        for suffix in ("町", "区", "市", "村"):
                            if stem.endswith(suffix) and len(stem) > len(suffix) + 1:
                                _add_with_kana_variants(places, stem[: -len(suffix)])
    if stations_path.exists():
        with stations_path.open(encoding="utf-8") as f:
            for line in f:
                _add_with_kana_variants(places, line.strip())
    places.discard("")
    return places


def _try_strip_place(s: str, sorted_places: list[str]) -> str | None:
    for place in sorted_places:
        if len(place) >= 2 and s.endswith(place) and len(s) > len(place):
            return s[: -len(place)].rstrip(TAIL_SEP_CHARS)
    return None


def _strip_tail(s: str, sorted_places: list[str]) -> str:
    """Iteratively strip trailing places, Roman numerals, direction words, and wing/unit suffixes.

    Also handles the {place}{number} pattern (e.g., 高島平2).
    """
    while s:
        prev = s
        s = ROMAN_NUMERAL_RE.sub("", s).rstrip(TAIL_SEP_CHARS)
        s = DIRECTION_WORD_RE.sub("", s).rstrip(TAIL_SEP_CHARS)
        s = WING_SUFFIX_RE.sub("", s).rstrip(TAIL_SEP_CHARS)
        stripped = _try_strip_place(s, sorted_places)
        if stripped is None and (m := TRAILING_DIGITS_RE.match(s)):
            base = m.group(1).rstrip(TAIL_SEP_CHARS)
            stripped = _try_strip_place(base, sorted_places)
        if stripped is not None:
            s = stripped
        if s == prev:
            break
    return s


def step2_strip_tails(
    normalized: list[tuple[str, str]], address_dir: Path, stations_path: Path
) -> list[tuple[str, str]]:
    """Return (raw, cleaned) pairs with trailing places, Roman numerals, and direction words removed."""
    cache = CACHE_DIR / "step2_cleaned.json"
    if (cached := _cache_load(cache)) is not None:
        out = [(x[0], x[1]) for x in cached]
        print(f"step2: loaded {len(out):,} from cache")
        return out
    places = _load_place_dict(address_dir, stations_path)
    sorted_places = sorted(places, key=len, reverse=True)
    print(f"step2: place dictionary {len(places):,} entries")
    out = [(raw, _strip_tail(n, sorted_places)) for raw, n in normalized]
    _cache_save(cache, out)
    return out


# --- Step 3: Extract katakana chunks + lexicon segmentation ---


def _extract_katakana_chunks(cleaned: list[tuple[str, str]]) -> Counter:
    counter: Counter = Counter()
    for _, c in cleaned:
        for chunk in KATAKANA_RE.findall(c):
            if len(chunk) >= MIN_CHUNK_LEN:
                counter[chunk] += 1
    return counter


def _lexicon_split(token: str) -> list[str]:
    """Longest-match scan: emit lexicon words; collect non-lexicon runs as single pieces.

    Treats SEPARATOR_CHARS (e.g. 中黒) as boundaries. Pieces that don't match the
    lexicon stay intact rather than being split further — splitting a brand name
    like アウル into ア+ウ+ル loses information, so we'd rather under-segment.
    """
    result: list[str] = []
    i = 0
    n = len(token)
    while i < n:
        if token[i] in SEPARATOR_CHARS:
            i += 1
            continue
        matched: str | None = None
        for word in LEXICON_SORTED:
            if token.startswith(word, i):
                matched = word
                break
        if matched is not None:
            result.append(matched)
            i += len(matched)
            continue
        j = i + 1
        while j < n and token[j] not in SEPARATOR_CHARS:
            if any(token.startswith(w, j) for w in LEXICON_SORTED):
                break
            j += 1
        result.append(token[i:j])
        i = j
    return result


def step3_segment(
    cleaned: list[tuple[str, str]],
) -> tuple[Counter, dict[str, list[str]]]:
    """Extract katakana chunks and segment them via lexicon longest-match."""
    cache = CACHE_DIR / "step3_lexicon.json"
    if (cached := _cache_load(cache)) is not None:
        chunk_counter: Counter = Counter(cached["chunk_counter"])
        chunk_to_tokens: dict[str, list[str]] = cached["chunk_to_tokens"]
        print(f"step3: loaded {len(chunk_counter):,} chunks from cache")
        return chunk_counter, chunk_to_tokens
    chunk_counter = _extract_katakana_chunks(cleaned)
    print(f"step3: {len(chunk_counter):,} unique chunks, {sum(chunk_counter.values()):,} occurrences")
    print(f"segmenting via lexicon ({len(LEXICON_SET)} entries)...")
    chunk_to_tokens = {chunk: _lexicon_split(chunk) for chunk in chunk_counter}
    _cache_save(cache, {"chunk_counter": dict(chunk_counter), "chunk_to_tokens": chunk_to_tokens})
    return chunk_counter, chunk_to_tokens


# --- Step 4: Aggregate sub-token counts ---


def step4_aggregate(chunk_counter: Counter, chunk_to_tokens: dict[str, list[str]]) -> Counter:
    """Aggregate sub-token counts from segmented chunks."""
    cache = CACHE_DIR / "step4_lexicon_tokens.json"
    if (cached := _cache_load(cache)) is not None:
        token_counter: Counter = Counter(cached)
        print(f"step4: loaded {len(token_counter):,} tokens from cache")
        return token_counter
    token_counter = Counter()
    for chunk, count in chunk_counter.items():
        for tok in chunk_to_tokens[chunk]:
            if len(tok) >= MIN_TOKEN_LEN:
                token_counter[tok] += count
    print(f"step4: {len(token_counter):,} unique tokens (len>={MIN_TOKEN_LEN})")
    _cache_save(cache, dict(token_counter))
    return token_counter


def _load_raw_titles(path: Path) -> list[str]:
    seen: set[str] = set()
    titles: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r.get("title")
            if not t or t in seen:
                continue
            seen.add(t)
            titles.append(t)
    return titles


@click.command()
@click.option("--force", is_flag=True, help="Ignore caches and recompute every step.")
def main(force: bool) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if force and CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        print("force: cleared cache")

    raw_titles = _load_raw_titles(LISTINGS_PATH)
    print(f"unique raw titles: {len(raw_titles):,}")

    normalized = step1_normalize(raw_titles)
    cleaned = step2_strip_tails(normalized, ADDRESS_DIR, STATIONS_PATH)
    chunk_counter, chunk_to_tokens = step3_segment(cleaned)
    token_counter = step4_aggregate(chunk_counter, chunk_to_tokens)

    print(f"\n--- top {TOP_N} sub-tokens ---")
    for rank, (tok, count) in enumerate(token_counter.most_common(TOP_N), 1):
        print(f"  {rank:>2}. {count:>6,}  {tok}")

    csv_path = OUTPUT_DIR / "token_counts.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["token", "count", "in_lexicon"])
        for tok, count in token_counter.most_common():
            w.writerow([tok, count, "Y" if tok in LEXICON_SET else ""])
    print(f"\nwrote: {csv_path}")

    unclassified = [(t, c) for t, c in token_counter.most_common() if t not in LEXICON_SET]
    print(f"\n--- top {TOP_N} unclassified tokens (lexicon candidates) ---")
    for rank, (tok, count) in enumerate(unclassified[:TOP_N], 1):
        print(f"  {rank:>2}. {count:>6,}  {tok}")

    sample_path = OUTPUT_DIR / "segmentation_sample.csv"
    with sample_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["raw", "cleaned", "segmented"])
        for raw, c in cleaned:
            chunks = KATAKANA_RE.findall(c)
            seg_parts = [" / ".join(chunk_to_tokens.get(ch, [ch])) for ch in chunks]
            w.writerow([raw, c, " || ".join(seg_parts)])
    print(f"wrote: {sample_path}")


if __name__ == "__main__":
    main()
