"""
Sync an S3 directory to a local directory, skipping files that are already in sync based on size.
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
@click.option("--max-concurrency", "-c", type=int, default=10, help="Max concurrent threads for multipart downloads")
@click.option("--skip-subdir", "-s", type=str, default="", help="Subdirectory names to skip (comma-separated)")
@click.option("--replace", "-r", is_flag=True, default=False, help="Delete all existing local files before download")
def main(input_dir, key_prefix, max_concurrency, skip_subdir, replace):
    base_path = Path(__file__).parent.parent / input_dir
    base_path.mkdir(parents=True, exist_ok=True)

    s3 = boto3.Session(profile_name=settings.aws_profile_name, region_name=settings.s3_region).client("s3")
    key_prefix = key_prefix.rstrip("/")

    # List S3 objects
    s3_objects = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=key_prefix + "/"):
        for obj in page.get("Contents", []):
            s3_objects[obj["Key"]] = obj["Size"]
    print(f"Found {len(s3_objects)} objects in S3")

    if replace:
        import shutil

        for child in base_path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        print(f"Deleted all existing local files in {input_dir}")

    skip_dirs = {s.strip() for s in skip_subdir.split(",") if s.strip()}

    # Collect files to download, skip already synced
    to_download = []
    for s3_key, s3_size in s3_objects.items():
        relative = s3_key[len(key_prefix) + 1 :]
        if not relative:
            continue
        relative_path = Path(relative)
        if skip_dirs and any(part in skip_dirs for part in relative_path.parts[:-1]):
            continue
        local_path = base_path / relative_path
        if local_path.exists() and local_path.stat().st_size == s3_size:
            continue
        to_download.append((s3_key, local_path, s3_size))

    total_bytes = sum(f[2] for f in to_download)
    print(f"Files to download: {len(to_download)} ({fmt_size(total_bytes)})")

    if not to_download:
        print("Already in sync")
        return

    lock = Lock()
    downloaded = 0
    downloaded_bytes = 0

    def download_one(item):
        nonlocal downloaded, downloaded_bytes
        s3_key, local_path, size = item
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(settings.s3_bucket_name, s3_key, str(local_path))
            with lock:
                downloaded += 1
                downloaded_bytes += size
                if downloaded % 50 == 0 or downloaded == len(to_download):
                    print(f"Downloaded {downloaded}/{len(to_download)} files ({fmt_size(downloaded_bytes)})")
        except Exception as e:
            print(f"Failed to download {s3_key}: {e}")

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = [pool.submit(download_one, item) for item in to_download]
        for f in as_completed(futures):
            f.result()

    print("Sync complete")


if __name__ == "__main__":
    main()
