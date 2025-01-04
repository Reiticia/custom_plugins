import json
from nonebot import on_command, get_driver
from nonebot.permission import SUPERUSER
from nonebot.matcher import Matcher
from nonebot.rule import to_me
from aiofiles import open
from typing import Optional
from nonebot_plugin_waiter import prompt, suggest

driver = get_driver()

import nonebot_plugin_localstore as store  # noqa: E402

_CONFIG_DIR = store.get_config_dir("people_like")

_PROFILE = _CONFIG_DIR / "people_like_multi_group.json"

PROPERTIES: dict[str, dict[str, str]] = json.loads(
    "{}" if not _PROFILE.exists() else text if (text := _PROFILE.read_text()) is not None else "{}"
)

_EXPECT_PROP_NAMES = ["prompt", "top_p", "top_k", "length"]


@on_command(cmd="gp", permission=SUPERUSER, rule=to_me()).handle()
async def get_property(matcher: Matcher):
    """通过指令获取群组属性"""
    global PROPERTIES, _EXPECT_PROP_NAMES
    resp = await prompt("请输入群号", timeout=60)
    if not resp:
        await matcher.finish("操作超时，指令中断")
    if not str(resp).isdigit():
        await matcher.finish("输入无效，指令中断")
    group_id = str(resp)
    resp = await suggest("请选择要获取的属性名", timeout=60, expect=_EXPECT_PROP_NAMES)
    if not resp:
        await matcher.finish("操作超时，指令中断")
    property_name = str(resp).upper()
    value = PROPERTIES.get(group_id, {}).get(property_name)
    ret = "None" if value is None else value
    await matcher.finish(ret)


@on_command(cmd="sp", permission=SUPERUSER, rule=to_me()).handle()
async def set_property(matcher: Matcher):
    """通过指令设置群组属性"""
    global PROPERTIES
    resp = await prompt("请输入群号", timeout=60)
    if not resp:
        await matcher.finish("操作超时，指令中断")
    if not str(resp).isdigit():
        await matcher.finish("输入无效，指令中断")
    group_id = str(resp)
    resp = await suggest("请选择要设置的属性名", timeout=60, expect=_EXPECT_PROP_NAMES)
    if not resp:
        await matcher.finish("操作超时，指令中断")
    property_name = str(resp).upper()
    resp = await prompt("请输入要设置的属性值", timeout=60)
    if not resp:
        await matcher.finish("操作超时，指令中断")
    value = str(resp)
    if value.lower() == "none":
        value = None
    # 赋值
    g_v = PROPERTIES.get(group_id, {})
    if value is None:
        g_v.pop(property_name, None)
    else:
        g_v.update({property_name: value})
    PROPERTIES.update({group_id: g_v})
    # 保存到文件
    await save_profile(matcher)
    ret: str = f"群{group_id}的属性{property_name}已设置为{value}"
    await matcher.finish(ret)


def get(group_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
    """获取群组属性"""
    global PROPERTIES
    return PROPERTIES.get(str(group_id), {}).get(key.upper(), default)


async def save_profile(matcher: Matcher):
    """保存配置文件"""
    global PROPERTIES, _PROFILE
    async with open(_PROFILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(PROPERTIES))
    await matcher.send("配置文件已保存")
