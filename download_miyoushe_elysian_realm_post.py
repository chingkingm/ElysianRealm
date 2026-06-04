#!/usr/bin/env python3
import argparse
import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

import httpx


DEFAULT_OUTPUT_ROOT = Path(r"D:\code\HoshinoBot\res\img\ElysianRealm")
POST_API = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
REFERER_BASE = "https://www.miyoushe.com/bh3/article/"
BASE_DIR = Path(__file__).resolve().parent
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VERSION_CACHE_LIMIT = 6


CN_NUMBERS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def extract_post_id(value):
    if value.isdigit():
        return value
    match = re.search(r"/article/(\d+)", value)
    if match:
        return match.group(1)
    match = re.search(r"post_id=(\d+)", value)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract post id from: {value}")


def cn_number(value):
    if value.isdigit():
        return int(value)
    if value in CN_NUMBERS:
        return CN_NUMBERS[value]
    if value.startswith("十") and len(value) == 2:
        return 10 + CN_NUMBERS.get(value[1], 0)
    if value.endswith("十") and len(value) == 2:
        return CN_NUMBERS.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return CN_NUMBERS.get(left, 1) * 10 + CN_NUMBERS.get(right, 0)
    raise ValueError(f"Cannot parse Chinese number: {value}")


def folder_name_from_title(title):
    match = re.search(r"[vV]\s*(\d+(?:\.\d+)*)\s*([一二两三四五六七八九十\d]+)期", title)
    if match:
        return f"v{match.group(1)}.{cn_number(match.group(2))}"

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or "miyoushe_post"


def version_dir_key(path):
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", path.name)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def version_dirs(output_root, newest_first=False):
    candidates = []
    for item in output_root.iterdir():
        if not item.is_dir():
            continue
        key = version_dir_key(item)
        if key:
            candidates.append((key, item))
    candidates.sort(key=lambda item: item[0], reverse=newest_first)
    return [item for _, item in candidates]


def fallback_image_key(path):
    return re.sub(r"_\d+$", "", path.stem)


def delete_root_fallback_images(output_root, image_key):
    deleted = 0
    pattern = re.compile(rf"{re.escape(image_key)}(?:_\d+)?$")
    for item in output_root.iterdir():
        if not item.is_file() or item.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if pattern.fullmatch(item.stem):
            item.unlink()
            deleted += 1
    return deleted


def prune_old_version_dirs(output_root, keep=VERSION_CACHE_LIMIT):
    removed = []
    directories = version_dirs(output_root)
    while len(directories) > keep:
        oldest = directories.pop(0)
        moved_images = 0
        deleted_root_images = 0
        images_by_key = {}
        for image in sorted(oldest.iterdir(), key=lambda path: path.name):
            if image.is_file() and image.suffix.lower() in IMAGE_SUFFIXES:
                images_by_key.setdefault(fallback_image_key(image), []).append(image)

        for image_key, images in images_by_key.items():
            deleted_root_images += delete_root_fallback_images(output_root, image_key)
            for image in images:
                image.replace(output_root / image.name)
                moved_images += 1
        shutil.rmtree(oldest)
        removed.append({
            "directory": str(oldest),
            "moved_images": moved_images,
            "deleted_root_images": deleted_root_images,
        })
    return removed


def version_phase_from_title(title):
    match = re.search(r"[vV]\s*(\d+(?:\.\d+)*)\s*([一二两三四五六七八九十\d]+)期", title)
    if not match:
        return None, None
    return match.group(1), cn_number(match.group(2))


async def fetch_post(post_id):
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
        resp = await client.get(
            POST_API,
            params={"post_id": post_id},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{REFERER_BASE}{post_id}",
                "x-rpc-client_type": "4",
                "x-rpc-app_version": "2.95.0",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("retcode") != 0:
        raise RuntimeError(f"Post API failed: {payload}")
    return payload["data"]["post"]["post"]


def image_ext(url):
    suffix = Path(httpx.URL(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"


async def download_image(client, url, path, referer):
    if path.exists() and path.stat().st_size > 0:
        return False

    resp = await client.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return True


async def download_post_images(post, output_root, post_id):
    title = post["subject"]
    folder = output_root / folder_name_from_title(title)
    folder.mkdir(parents=True, exist_ok=True)

    images = post.get("images") or []
    existing_images = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    ]
    if len(existing_images) >= len(images):
        print(f"found {len(existing_images)} existing images in {folder}; skip download")
        return folder

    referer = f"{REFERER_BASE}{post_id}"
    downloaded = []
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, trust_env=False) as client:
        for index, url in enumerate(images, 1):
            path = folder / f"{index:02d}{image_ext(url)}"
            changed = await download_image(client, url, path, referer)
            downloaded.append(path)
            print(f"{'downloaded' if changed else 'exists'} {path.name}")

    (folder / "post_meta.json").write_text(
        json.dumps(
            {
                "post_id": post_id,
                "title": title,
                "source_url": referer,
                "image_count": len(images),
                "images": images,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return folder


async def run_rename(folder, report_path, threshold, margin):
    command = [
        sys.executable,
        str(Path(__file__).with_name("identify_valkyrie_guide_images.py")),
        "--guide-dir",
        str(folder),
        "--report",
        str(report_path),
        "--threshold",
        str(threshold),
        "--margin",
        str(margin),
        "--rename",
    ]
    process = await asyncio.create_subprocess_exec(*command)
    return_code = await process.wait()
    if return_code:
        raise RuntimeError(f"Command failed with exit code {return_code}: {' '.join(command)}")


async def run_wiki_refresh():
    scripts = [
        "scrape_bh3_valkyries.py",
        "download_bh3_valkyrie_images.py",
    ]
    for script in scripts:
        command = [sys.executable, str(Path(__file__).with_name(script))]
        print(f"running {' '.join(command)}", flush=True)
        process = await asyncio.create_subprocess_exec(*command)
        return_code = await process.wait()
        if return_code:
            raise RuntimeError(f"Command failed with exit code {return_code}: {' '.join(command)}")


async def amain():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("post", help="Miyoushe article URL or post id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--no-rename", action="store_true", help="download only; do not identify and rename")
    parser.add_argument(
        "--skip-wiki-refresh",
        action="store_true",
        help="do not refresh wiki valkyrie data before recognizing first-phase posts",
    )
    parser.add_argument("--threshold", type=float, default=35.0)
    parser.add_argument("--margin", type=float, default=8.0)
    args = parser.parse_args()

    post_id = extract_post_id(args.post)
    post = await fetch_post(post_id)
    folder = await download_post_images(post, args.output_root, post_id)

    print(f"\nTitle: {post['subject']}")
    print(f"Directory: {folder}")

    if not args.no_rename:
        version, phase = version_phase_from_title(post["subject"])
        if phase == 1 and not args.skip_wiki_refresh:
            print(f"\n{version} phase {phase}: refreshing wiki valkyrie data before recognition", flush=True)
            await run_wiki_refresh()
        elif phase == 1:
            print(f"\n{version} phase {phase}: skipped wiki refresh", flush=True)

        report = BASE_DIR / "data" / f"{folder.name}_guide_image_matches.csv"
        await run_rename(folder, report, args.threshold, args.margin)
        removed = prune_old_version_dirs(args.output_root)
        for item in removed:
            print(f"removed old version directory {item['directory']}; moved {item['moved_images']} images to root")


if __name__ == "__main__":
    asyncio.run(amain())
