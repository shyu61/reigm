# reigm

## Usage
```bash
nohup env PYTHONUNBUFFERED=1 \
  uv run exp/001_fetch_suumo.py --pages 2665 >> logs/001_fetch_suumo.log 2>&1 &
```
