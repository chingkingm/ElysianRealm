#!/usr/bin/env python3
import asyncio
import csv
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import httpx


APP_SN = "bh3_wiki"
API_BASE = "https://act-api-takumi-static.mihoyo.com/common/blackboard/bh3_wiki"
REFERER = "https://baike.mihoyo.com/bh3/wiki/channel/map/17/18?bbs_presentation_style=no_header"
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data"
ALIAS_PATH = BASE_DIR / "alias.json"
ALIAS_TEMPLATE_PATH = BASE_DIR / "alias_template.json"
ALIAS_SEPARATORS = re.compile(r"[、,，]")
IGNORED_ALIASES = {"", "暂无", "无", "-"}


async def fetch_json(client, url):
    resp = await client.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": REFERER,
            "Accept": "application/json, text/plain, */*",
        },
    )
    resp.raise_for_status()
    return resp.json()


async def api_get(client, path, params):
    payload = await fetch_json(
        client,
        str(httpx.URL(f"{API_BASE}{path}", params={"app_sn": APP_SN, **params})),
    )
    if payload.get("retcode") != 0:
        raise RuntimeError(f"API failed: {path} {payload}")
    return payload["data"]


def decode_template_data(text):
    for match in re.finditer(r'data-data="([^"]+)"', text or ""):
        raw = html.unescape(match.group(1))
        decoded = unquote(raw)
        try:
            yield from json.loads(decoded)
        except json.JSONDecodeError:
            continue


def set_field(result, name, value):
    if not name:
        return
    if name == "名称":
        result["name"] = value
    elif name == "别名":
        result["alias"] = value
    elif name == "外文名":
        result["foreign_name"] = value


def extract_detail_fields(content):
    result = {"name": "", "alias": "", "foreign_name": "", "poster_image": ""}

    for tab in content.get("contents") or []:
        for block in decode_template_data(tab.get("text")):
            data = block.get("data") or {}

            if not result["poster_image"] and data.get("avatar"):
                result["poster_image"] = data["avatar"]

            for field in data.get("mainFields") or []:
                set_field(result, field.get("nameL"), field.get("valueL", ""))
                set_field(result, field.get("nameR"), field.get("valueR", ""))

    return result


async def scrape():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
        channel_data = await api_get(
            client,
            "/v1/home/content/list",
            {"channel_id": 18, "page_num": 1, "page_size": 200},
        )
        channel = channel_data["list"][0]

        entries = channel.get("list") or []
        rows = []
        for index, entry in enumerate(entries, 1):
            content_id = entry["content_id"]
            detail = (await api_get(client, "/v1/content/info", {"content_id": content_id}))["content"]
            fields = extract_detail_fields(detail)

            row = {
                "content_id": content_id,
                "name": fields["name"] or detail.get("title") or entry.get("title", ""),
                "alias": fields["alias"],
                "foreign_name": fields["foreign_name"],
                "avatar_image": entry.get("icon", ""),
                "poster_image": fields["poster_image"],
                "detail_url": f"https://baike.mihoyo.com/bh3/wiki/content/{content_id}/detail?bbs_presentation_style=no_header",
            }
            rows.append(row)
            print(f"[{index:03d}/{len(entries)}] {row['name']}", flush=True)
            await asyncio.sleep(0.05)

        return rows


def write_outputs(rows):
    OUTPUT_DIR.mkdir(exist_ok=True)
    json_path = OUTPUT_DIR / "bh3_valkyries.json"
    csv_path = OUTPUT_DIR / "bh3_valkyries.csv"

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "content_id",
        "name",
        "alias",
        "foreign_name",
        "avatar_image",
        "poster_image",
        "detail_url",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return json_path, csv_path


def split_aliases(value):
    return [
        item.strip()
        for item in ALIAS_SEPARATORS.split(value or "")
        if item.strip() and item.strip() not in IGNORED_ALIASES
    ]


def load_alias_data():
    if not ALIAS_PATH.exists():
        data = json.loads(ALIAS_TEMPLATE_PATH.read_text(encoding="utf-8"))
        ALIAS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        return data
    return json.loads(ALIAS_PATH.read_text(encoding="utf-8"))


def sync_alias_file(rows):
    data = load_alias_data()
    used_aliases = {
        alias
        for name, aliases in data.items()
        for alias in [name, *(aliases or [])]
    }
    added_names = []
    added_aliases = 0

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue

        wiki_aliases = []
        for alias in split_aliases(row.get("alias", "")):
            if alias != name and alias not in used_aliases:
                wiki_aliases.append(alias)
                used_aliases.add(alias)

        if name not in data:
            data[name] = wiki_aliases
            used_aliases.add(name)
            added_names.append(name)
            added_aliases += len(wiki_aliases)
            continue

        existing = list(data.get(name) or [])
        for alias in wiki_aliases:
            existing.append(alias)
            added_aliases += 1
        data[name] = existing

    ALIAS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    return added_names, added_aliases


async def amain():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = await scrape()
    json_path, csv_path = write_outputs(rows)
    added_names, added_aliases = sync_alias_file(rows)
    print(f"\nWrote {len(rows)} rows")
    print(json_path)
    print(csv_path)
    print(f"Synced alias.json: added {len(added_names)} names and {added_aliases} aliases")
    if added_names:
        print("New names: " + "、".join(added_names))


if __name__ == "__main__":
    asyncio.run(amain())
