import datetime
import json
import os
import re

from hoshino import Service, priv, typing
from nonebot import MessageSegment

sv = Service("刻印", enable_on_default=True, visible=True)


def trans_alias(alias) -> str:
    """转换别名"""
    with open(
        os.path.join(os.path.dirname(__file__), "alias.json"), "r", encoding="utf8"
    ) as f:
        data = json.load(f)
        f.close()
    for k in data:
        if alias == k or alias in data[k]:
            return k
    raise KeyError(f"没有找到{alias}的数据，请检查输入")


@sv.on_prefix(("刻印"))
async def show_buff(bot, ev):
    msg = ev.message.extract_plain_text().strip()
    if not msg:
        return
    try:
        valkyrie = trans_alias(msg)
    except KeyError as e:
        await bot.send(ev, f"{e}\n如果确定没输错,请联系管理员添加别名.")
        return
    # ms = MessageSegment.text("没正式更新")
    select_im = []
    for im in os.listdir(os.path.join(os.path.dirname(__file__), "image")):
        if im.startswith(valkyrie):
            select_im.append(os.path.join(os.path.dirname(__file__), "image", im))
    images = MessageSegment.text("")
    for im in select_im:
        images = images + MessageSegment.image(f"file:///{im}")
    await bot.send(ev, images)
    return


@sv.on_prefix("刻印别名添加")
async def add_alias(bot, ev: typing.CQEvent):
    if not priv.check_priv(ev, priv.SU):
        return
    msg = str(ev.message.extract_plain_text())
    try:
        valkyrie, alias = re.split(":|：", msg)
    except:
        return
    try:
        valkyrie = trans_alias(valkyrie)
    except:
        return
    with open(
        os.path.join(os.path.dirname(__file__), "alias.json"), "r", encoding="utf8"
    ) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    with open(
        os.path.join(os.path.dirname(__file__), "alias.json"), "w", encoding="utf8"
    ) as f:
        alias_data = set(data[valkyrie])
        alias_data.add(alias)
        data.update({valkyrie: list(alias_data)})
        json.dump(data, f, ensure_ascii=False, indent=4)
    await bot.send(ev, f"{valkyrie}别名:{alias}更新完成。\n当前记录的别名如下\n{alias_data}")
    with open(
        os.path.join(os.path.dirname(__file__), "record.txt"), "a+", encoding="utf8"
    ) as rec:
        rec.write(
            f"{ev.user_id}:{ev.group_id},{valkyrie}-{alias}   {datetime.datetime.today()}\n"
        )
        rec.close()


if __name__ == "__main__":
    pass
