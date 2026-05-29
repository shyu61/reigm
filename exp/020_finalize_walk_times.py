"""Finalize the walk-times dataset by swapping the unresolvable originals for their
stratified replacements.

exp/018's walk_times.csv still carries the original `building_unresolved` rows
(buildings Google Places had no POI for) alongside the replacement pairs exp/019
drew to compensate for them, plus a couple of `no_route` rows (resolved on Places
but Routes found no walkable path). Finalizing keeps only `ok` rows: the
replacements are already resolved in that same file, so every replaced
(station, stated_min) cell keeps its allocation via the replacement.

replacement_pairs.csv is read only to verify the swap: each replacement key should
be present and resolved in the output, and the script reports the before/after
counts so the substitution is auditable.

No API calls — pure local CSV transform. Output mirrors exp/018's columns.
"""

import csv
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
DATA_DIR = SCRIPT_PATH.parent.parent / "data"
WALK_TIMES_CSV = DATA_DIR / "018_fetch_walk_times" / "walk_times.csv"
REPLACEMENTS_CSV = DATA_DIR / "019_resample_unresolved" / "replacement_pairs.csv"
OUTPUT_DIR = DATA_DIR / SCRIPT_PATH.stem
OUTPUT_CSV = OUTPUT_DIR / "walk_times.csv"

# Only fully resolved pairs are kept; every other status is a dead/incomplete row
# (building_unresolved = no Places match, no_route = no walkable path found).
KEEP_STATUS = "ok"


def _pair_key(row: dict) -> tuple[str, str, str, str]:
    return (row["building_title"], row["building_address"], row["station"], str(row["stated_min"]))


def main() -> None:
    with WALK_TIMES_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    print(f"read {len(rows):,} rows from {WALK_TIMES_CSV.name}")

    with REPLACEMENTS_CSV.open(encoding="utf-8") as f:
        replacement_keys = {_pair_key(r) for r in csv.DictReader(f)}
    print(f"replacement pairs: {len(replacement_keys):,}")

    kept = [r for r in rows if r["status"] == KEEP_STATUS]
    dropped = len(rows) - len(kept)
    dropped_by_status: dict[str, int] = {}
    for r in rows:
        if r["status"] != KEEP_STATUS:
            dropped_by_status[r["status"]] = dropped_by_status.get(r["status"], 0) + 1

    # Verify every replacement landed as a resolved row in the kept set.
    kept_by_key = {_pair_key(r): r for r in kept}
    present = sum(1 for k in replacement_keys if k in kept_by_key)
    resolved = sum(1 for k in replacement_keys if kept_by_key.get(k, {}).get("status") == "ok")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(kept)

    drop_detail = ", ".join(f"{s}={n:,}" for s, n in sorted(dropped_by_status.items(), key=lambda kv: -kv[1]))
    print(f"\ndropped {dropped:,} non-ok rows ({drop_detail}); wrote {len(kept):,} rows: {OUTPUT_CSV}")
    print(f"replacements present in output: {present:,}/{len(replacement_keys):,} (resolved: {resolved:,})")
    print(f"\nfinal: {len(kept):,} rows, all status=ok")


if __name__ == "__main__":
    main()
