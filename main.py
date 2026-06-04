import datetime
import asyncio
import json
import re
from pathlib import Path

from hoshino import Service, priv, typing, R
from nonebot import MessageSegment

from .download_miyoushe_elysian_realm_post import (
    download_post_images,
    extract_post_id,
    fetch_post,
    IMAGE_SUFFIXES,
    prune_old_version_dirs,
    run_rename,
    run_wiki_refresh,
    version_dirs,
    version_phase_from_title,
)
from .download_miyoushe_user_elysian_posts import fetch_user_posts

sv = Service("刻印", enable_on_default=True, visible=True)
MIYOUSHE_ACCOUNT_URL = "https://www.miyoushe.com/bh3/accountCenter/postList?id=5625196"
MIYOUSHE_ARTICLE_RE = re.compile(r"https?://www\.miyoushe\.com/bh3/article/\d+")
UPDATE_LOCK = asyncio.Lock()
BASE_DIR = Path(__file__).resolve().parent
ALIAS_PATH = BASE_DIR / "alias.json"
ALIAS_TEMPLATE_PATH = BASE_DIR / "alias_template.json"
RECORD_PATH = BASE_DIR / "record.txt"


def is_recommend_buff_post(post) -> bool:
    title = post.get("subject", "")
    version, phase = version_phase_from_title(title)
    return bool(version and phase and "推荐角色" in title and "BUFF表" in title)


async def find_latest_first_phase_post():
    async for post in fetch_user_posts("5625196"):
        version, phase = version_phase_from_title(post.get("subject", ""))
        if phase == 1 and is_recommend_buff_post(post):
            return post
    raise RuntimeError("没有找到最新的一期推荐角色BUFF表帖子")


async def run_engraving_update(article_url: str = ""):
    img_root = Path(R.img("ElysianRealm/").path)

    if article_url:
        post = await fetch_post(extract_post_id(article_url))
    else:
        post = await find_latest_first_phase_post()

    version, phase = version_phase_from_title(post["subject"])
    folder = await download_post_images(post, img_root, post["post_id"])

    if phase == 1:
        await run_wiki_refresh()

    report = Path(__file__).with_name("data") / f"{folder.name}_guide_image_matches.csv"
    await run_rename(folder, report, 35.0, 8.0)

    images = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    ]
    removed = prune_old_version_dirs(img_root)
    return {
        "title": post["subject"],
        "version": version,
        "phase": phase,
        "folder": str(folder),
        "image_count": len(images),
        "removed_dirs": removed,
        "report": str(report),
        "source": f"https://www.miyoushe.com/bh3/article/{post['post_id']}",
    }


def find_images_in_dir(img_root: Path, directory: Path, valkyrie: str):
    selected = []
    for item in sorted(directory.iterdir(), key=lambda path: path.name):
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES and item.name.startswith(valkyrie):
            rel = item.relative_to(img_root).as_posix()
            selected.append((rel, item))
    return selected


def find_valkyrie_images(valkyrie: str):
    img_root = Path(R.img("ElysianRealm/").path)

    for directory in version_dirs(img_root, newest_first=True)[:6]:
        selected = find_images_in_dir(img_root, directory, valkyrie)
        if selected:
            return directory.name, selected

    selected = find_images_in_dir(img_root, img_root, valkyrie)
    if selected:
        return "过时的版本", selected
    return "", []


def trans_alias(alias) -> str:
    """转换别名"""
    check_aliasfile()
    data = json.loads(ALIAS_PATH.read_text(encoding="utf8"))
    for k in data:
        if alias == k or alias in data[k]:
            return k
    raise KeyError(f"没有找到{alias}的数据，请检查输入")


def check_aliasfile():
    """检查alias.json文件是否存在,不存在则复制alias_template.json内容并新建alias.json"""
    if ALIAS_PATH.exists():
        return
    data = json.loads(ALIAS_TEMPLATE_PATH.read_text(encoding="utf8"))
    ALIAS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf8",
    )


@sv.on_prefix("刻印更新")
async def update_engraving(bot, ev: typing.CQEvent):
    if not priv.check_priv(ev, priv.SU):
        return

    msg = ev.message.extract_plain_text().strip()
    match = MIYOUSHE_ARTICLE_RE.search(msg)
    article_url = match.group(0) if match else ""

    if UPDATE_LOCK.locked():
        await bot.send(ev, "已有刻印更新任务正在运行，请稍后再试。")
        return

    async with UPDATE_LOCK:
        source = article_url or MIYOUSHE_ACCOUNT_URL
        await bot.send(ev, f"开始更新刻印资源：{source}")
        try:
            result = await run_engraving_update(article_url)
        except Exception as e:
            await bot.send(ev, f"刻印更新失败：{e}")
            return

    removed_text = ""
    if result["removed_dirs"]:
        removed_text = "\n清理旧目录：" + "、".join(
            Path(item["directory"]).name for item in result["removed_dirs"]
        )

    await bot.send(
        ev,
        "刻印更新完成\n"
        f"标题：{result['title']}\n"
        f"目录：{result['folder']}\n"
        f"图片数：{result['image_count']}\n"
        f"来源：{result['source']}"
        f"{removed_text}",
    )


@sv.on_prefix(("刻印"))
async def show_buff(bot, ev):
    msg = ev.message.extract_plain_text().strip()
    if not msg:
        return
    if msg.startswith("更新"):
        return
    try:
        valkyrie = trans_alias(msg)
    except KeyError as e:
        await bot.send(ev, f"{e}\n如果确定没输错,请联系管理员添加别名.")
        return
    directory_name, select_im = find_valkyrie_images(valkyrie)
    if not select_im:
        await bot.send(ev, f"没有找到{valkyrie}的刻印攻略图。")
        return
    images = MessageSegment.text("")
    for rel, _ in select_im:
        images = images + R.img("ElysianRealm/", rel).cqcode
    await bot.send(ev, MessageSegment.text(f"{directory_name}\n") + images)


@sv.on_prefix("刻印别名添加")
async def add_alias(bot, ev: typing.CQEvent):
    if not priv.check_priv(ev, priv.SU):
        return
    msg = str(ev.message.extract_plain_text())
    try:
        valkyrie, alias = re.split(":|：", msg)
    except IndexError:
        return
    try:
        valkyrie = trans_alias(valkyrie)
    except:
        return
    check_aliasfile()
    data = json.loads(ALIAS_PATH.read_text(encoding="utf8"))
    assert isinstance(data, dict)
    alias_data = set(data[valkyrie])
    alias_data.add(alias)
    data.update({valkyrie: list(alias_data)})
    ALIAS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf8",
    )
    await bot.send(ev, f"{valkyrie}别名:{alias}更新完成。\n当前记录的别名如下\n{alias_data}")
    with RECORD_PATH.open("a+", encoding="utf8") as rec:
        rec.write(f"{ev.user_id}:{ev.group_id},{valkyrie}-{alias}   {datetime.datetime.today()}\n")


if __name__ == "__main__":
    pass
