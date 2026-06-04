#!/usr/bin/env python3
import asyncio
import csv
import json
import sys
from pathlib import Path

import httpx


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data/bh3_valkyries.json"
OUTPUT_DIR = BASE_DIR / "data/images/valkyries_by_id"
JSON_OUTPUT = BASE_DIR / "data/bh3_valkyries_with_local_images.json"
CSV_OUTPUT = BASE_DIR / "data/bh3_valkyries_with_local_images.csv"
REFERER = "https://baike.mihoyo.com/bh3/wiki/channel/map/17/18?bbs_presentation_style=no_header"


def extension_from_url(url):
    suffix = Path(httpx.URL(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".png"


async def download(client, url, path):
    if path.exists() and path.stat().st_size > 0:
        return

    resp = await client.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": REFERER,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    resp.raise_for_status()
    path.write_bytes(resp.content)


async def amain():
    sys.stdout.reconfigure(encoding="utf-8")

    rows = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    updated = []
    total = len(rows)
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, trust_env=False) as client:
        for index, row in enumerate(rows, 1):
            folder = OUTPUT_DIR / str(row["content_id"])
            folder.mkdir(parents=True, exist_ok=True)

            avatar_path = folder / f"avatar{extension_from_url(row['avatar_image'])}"
            poster_path = folder / f"poster{extension_from_url(row['poster_image'])}"

            await download(client, row["avatar_image"], avatar_path)
            await asyncio.sleep(0.03)
            await download(client, row["poster_image"], poster_path)
            await asyncio.sleep(0.03)

            item = dict(row)
            item["avatar_image_local"] = str(avatar_path)
            item["poster_image_local"] = str(poster_path)
            updated.append(item)

            print(f"[{index:03d}/{total}] {row['name']}", flush=True)

    JSON_OUTPUT.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "content_id",
        "name",
        "alias",
        "foreign_name",
        "avatar_image",
        "avatar_image_local",
        "poster_image",
        "poster_image_local",
        "detail_url",
    ]
    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated)

    print(f"\nDownloaded {total * 2} images")
    print(JSON_OUTPUT)
    print(CSV_OUTPUT)


if __name__ == "__main__":
    asyncio.run(amain())
