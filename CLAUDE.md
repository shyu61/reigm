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
