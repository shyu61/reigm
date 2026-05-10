.PHONY: sync sync-r rsync rsync-r

sync:
	uv run scripts/sync_dir.py -i data -k data

sync-r:
	uv run scripts/sync_dir.py -i data -k data -r

rsync:
	uv run scripts/rsync_dir.py -i data -k data

rsync-r:
	uv run scripts/rsync_dir.py -i data -k data -r
