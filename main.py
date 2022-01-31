import os
import json
import re
from hoshino import Service
from nonebot import MessageSegment
sv = Service("刻印",enable_on_default=False,visible=True)

def trans_alias(alias) -> str:
    """转换别名"""
    with open(os.path.join(os.path.dirname(__file__),'alias.json'),'r',encoding='utf8') as f:
        data = json.load(f)
        f.close()
    for k in data:
        if alias == k or alias in data[k]:
            return k
    raise KeyError(f'没有找到{alias}的数据，请检查输入')

    
@sv.on_prefix(("刻印"))
async def show_buff(bot,ev):
    msg = ev.message.extract_plain_text()
    try:
        valkyrie = trans_alias(msg)
    except KeyError as e:
        await bot.send(ev,f"{e}\n如果确定没输错,请联系管理员添加别名.")
        return
    image_path = os.path.join(os.path.dirname(__file__),f'image\\{valkyrie}.jpg')
    if not os.path.exists(image_path):
        await bot.send(ev,f"新角色还没更新,速去催胱忠!")
        return
    image = MessageSegment.image(f'file:///{image_path}')
    if valkyrie == '雷之律者':
        image_path_2 = r'C:\HoshinoBot\hoshino\modules\paradise\image\雷之律者_2.jpg'
        image = image + MessageSegment.image(f'file:///{image_path_2}')
    await bot.send(ev,f"还没更新,谨慎选择{image}")
    return
@sv.on_prefix("刻印别名添加")
async def add_alias(bot,ev):
    msg = str(ev.message.extract_plain_text())
    try:
        valkyrie,alias = re.split(":|：",msg)
    except:
        return
    try:
        valkyrie = trans_alias(valkyrie)
    except:
        return
    with open(os.path.join(os.path.dirname(__file__),'alias.json'),'r',encoding='utf8') as f:
        data = json.load(f)
    assert isinstance(data,dict)
    with open(os.path.join(os.path.dirname(__file__),'alias.json'),'w',encoding='utf8') as f:
        alias_data = set(data[valkyrie])
        alias_data.add(alias)
        data.update(alias_data)
        json.dump(data,f)
    await bot.send(ev,f"{valkyrie}别名:{alias}更新完成。\n当前记录的别名如下\n{alias_data}")

if __name__ == '__main__':
    pass