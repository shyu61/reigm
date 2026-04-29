.PHONY: sync sync-r rsync rsync-r

sync:
	uv run scripts/sync_dir.py -i data -k data
	uv run scripts/sync_dir.py -i logs -k logs

sync-r:
	uv run scripts/sync_dir.py -i data -k data -r
	uv run scripts/sync_dir.py -i logs -k logs -r

rsync:
	uv run scripts/rsync_dir.py -i data -k data
	uv run scripts/rsync_dir.py -i logs -k logs

rsync-r:
	uv run scripts/rsync_dir.py -i data -k data -r
	uv run scripts/rsync_dir.py -i logs -k logs -r
