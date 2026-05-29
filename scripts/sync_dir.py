"""
Sync a local directory to S3, skipping files that are already in sync based on size.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import boto3
import click
from settings import settings


def fmt_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n_bytes) < 1024:
            return f"{n_bytes:.2f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.2f} PB"


@click.command()
@click.option("--input-dir", "-i", type=str, required=True)
@click.option("--key-prefix", "-k", type=str, required=True)
@click.option("--max-concurrency", "-c", type=int, default=10, help="Max concurrent threads for multipart uploads")
@click.option("--skip-subdir", "-s", type=str, default="", help="Subdirectory names to skip (comma-separated)")
def main(input_dir, key_prefix, max_concurrency, skip_subdir):
    base_path = Path(__file__).parent.parent / input_dir

    if not base_path.exists() or not base_path.is_dir():
        print(f"{input_dir} is not a valid directory")
        return

    s3 = boto3.Session(profile_name=settings.aws_profile_name, region_name=settings.s3_region).client("s3")
    key_prefix = key_prefix.rstrip("/")

    # List existing S3 objects for sync comparison
    existing = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=key_prefix + "/"):
        for obj in page.get("Contents", []):
            existing[obj["Key"]] = obj["Size"]
    print(f"Found {len(existing)} existing objects in S3")

    skip_dirs = {s.strip() for s in skip_subdir.split(",") if s.strip()}

    # Collect local files, skip already synced
    local_files = []
    for file_path in base_path.rglob("*"):
        if skip_dirs and any(part in skip_dirs for part in file_path.relative_to(base_path).parts[:-1]):
            continue
        if file_path.is_file() and file_path.name != ".DS_Store":
            relative_path = file_path.relative_to(base_path)
            s3_key = f"{key_prefix}/{relative_path.as_posix()}"
            local_size = file_path.stat().st_size
            if s3_key in existing and existing[s3_key] == local_size:
                continue
            local_files.append((file_path, s3_key, local_size))

    total_bytes = sum(f[2] for f in local_files)
    print(f"Files to upload: {len(local_files)} ({fmt_size(total_bytes)})")

    if not local_files:
        print("Already in sync")
        return

    lock = Lock()
    uploaded = 0
    uploaded_bytes = 0

    def upload_one(item):
        nonlocal uploaded, uploaded_bytes
        file_path, s3_key, size = item
        try:
            s3.upload_file(str(file_path), settings.s3_bucket_name, s3_key)
            with lock:
                uploaded += 1
                uploaded_bytes += size
                if uploaded % 50 == 0 or uploaded == len(local_files):
                    print(f"Uploaded {uploaded}/{len(local_files)} files ({fmt_size(uploaded_bytes)})")
        except Exception as e:
            print(f"Failed to upload {file_path.relative_to(base_path)}: {e}")

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = [pool.submit(upload_one, item) for item in local_files]
        for f in as_completed(futures):
            f.result()

    print("Sync complete")


if __name__ == "__main__":
    main()
