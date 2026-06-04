#!/usr/bin/env python3
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

try:
    from .download_miyoushe_elysian_realm_post import (
        BASE_DIR,
        DEFAULT_OUTPUT_ROOT,
        folder_name_from_title,
        prune_old_version_dirs,
        run_rename,
        run_wiki_refresh,
        version_phase_from_title,
    )
except ImportError:
    from download_miyoushe_elysian_realm_post import (
        BASE_DIR,
        DEFAULT_OUTPUT_ROOT,
        folder_name_from_title,
        prune_old_version_dirs,
        run_rename,
        run_wiki_refresh,
        version_phase_from_title,
    )


USER_POST_API = "https://bbs-api.miyoushe.com/post/wapi/userPost"
ACCOUNT_REFERER = "https://www.miyoushe.com/bh3/accountCenter/postList"
ARTICLE_REFERER = "https://www.miyoushe.com/bh3/article/"


def parse_uid(value):
    if value.isdigit():
        return value
    match = re.search(r"[?&]id=(\d+)", value)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract uid from: {value}")


async def fetch_user_posts(uid, limit_pages=None):
    offset = "0"
    page = 0
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{ACCOUNT_REFERER}?id={uid}",
        "x-rpc-client_type": "4",
        "x-rpc-app_version": "2.95.0",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
        while True:
            page += 1
            resp = await client.get(
                USER_POST_API,
                params={"uid": uid, "size": 20, "offset": offset},
                headers=headers,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("retcode") != 0:
                raise RuntimeError(f"User post API failed: {payload}")

            data = payload["data"]
            for item in data.get("list") or []:
                yield item["post"]

            if data.get("is_last") or not data.get("next_offset"):
                break
            if limit_pages and page >= limit_pages:
                break
            offset = data["next_offset"]
            await asyncio.sleep(0.05)


def version_key(version, phase):
    return tuple(int(part) for part in version.split(".")) + (phase,)


def is_target_post(post, after):
    title = post.get("subject", "")
    version, phase = version_phase_from_title(title)
    if not version:
        return False
    if version_key(version, phase) <= after:
        return False
    return "推荐角色" in title and "BUFF表" in title


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


async def download_post_from_list_data(post, output_root):
    title = post["subject"]
    post_id = post["post_id"]
    folder = output_root / folder_name_from_title(title)
    folder.mkdir(parents=True, exist_ok=True)

    images = post.get("images") or []
    existing_images = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ]
    if len(existing_images) < len(images):
        referer = f"{ARTICLE_REFERER}{post_id}"
        async with httpx.AsyncClient(timeout=45, follow_redirects=True, trust_env=False) as client:
            for index, url in enumerate(images, 1):
                path = folder / f"{index:02d}{image_ext(url)}"
                changed = await download_image(client, url, path, referer)
                print(f"{folder.name}: {'downloaded' if changed else 'exists'} {path.name}")
    else:
        print(f"{folder.name}: found {len(existing_images)} existing images; skip download")

    (folder / "post_meta.json").write_text(
        json.dumps(
            {
                "post_id": post_id,
                "title": title,
                "source_url": f"{ARTICLE_REFERER}{post_id}",
                "image_count": len(images),
                "images": images,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return folder


async def amain():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("account", help="Miyoushe account postList URL or uid")
    parser.add_argument("--after", default="8.0.1", help="exclusive lower bound as version.phase, default: 8.0.1")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--skip-wiki-refresh", action="store_true")
    parser.add_argument("--threshold", type=float, default=35.0)
    parser.add_argument("--margin", type=float, default=8.0)
    parser.add_argument("--limit-pages", type=int)
    args = parser.parse_args()

    uid = parse_uid(args.account)
    after = tuple(int(part) for part in args.after.split("."))
    selected = [
        post
        async for post in fetch_user_posts(uid, args.limit_pages)
        if is_target_post(post, after)
    ]
    selected.sort(key=lambda post: version_key(*version_phase_from_title(post["subject"])))

    print(f"selected {len(selected)} posts after {args.after}:")
    for post in selected:
        version, phase = version_phase_from_title(post["subject"])
        print(f"- v{version}.{phase} {post['post_id']} {post['subject']}")

    if not selected:
        return

    if not args.skip_wiki_refresh and any(version_phase_from_title(post["subject"])[1] == 1 for post in selected):
        print("\nselected posts include first-phase guides; refreshing wiki valkyrie data once", flush=True)
        await run_wiki_refresh()

    for post in selected:
        folder = await download_post_from_list_data(post, args.output_root)
        report = BASE_DIR / "data" / f"{folder.name}_guide_image_matches.csv"
        await run_rename(folder, report, args.threshold, args.margin)

    removed = prune_old_version_dirs(args.output_root)
    for item in removed:
        print(f"removed old version directory {item['directory']}; moved {item['moved_images']} images to root")


if __name__ == "__main__":
    asyncio.run(amain())
