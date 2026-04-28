# Project Guidelines

## File Organization

- `src/` — Reusable code (utilities, shared modules, common logic)
- `exp/` — One-off experiments and non-reusable scripts
- When an exp script outputs files, save them under `data/{exp_file_name}/` (e.g., `exp/001_check_llm_connectivity.py` → `data/001_check_llm_connectivity/`)

## Running Scripts

- Run Python scripts with `uv run <file>`

## Settings

- Use `pydantic-settings` via `src/settings.py` for environment variables. The `.env` file is loaded automatically.

## Imports

- When importing from `src/`, use `from settings import ...` (not `from src.settings import ...`). The `src/` prefix is not needed because `uv run` adds it to the Python path.

## Logging / Output

- Use `print()` rather than `click.echo()` for stdout output, even in click-based CLIs.

## Exp Scripts

- In `exp/` scripts, prefer module-level constants over click options for values that don't need to vary across runs (e.g., output paths). Reserve click options for inputs the user is likely to override.
- Derive the output directory from the script filename rather than hardcoding it, so renaming the script automatically retargets its output:

  ```python
  SCRIPT_PATH = Path(__file__).resolve()
  OUTPUT_DIR = SCRIPT_PATH.parent.parent / "data" / SCRIPT_PATH.stem
  ```
