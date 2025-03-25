import json
from nonebot import on_command, get_driver
from nonebot.permission import SUPERUSER
from nonebot.matcher import Matcher
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent
from aiofiles import open
from nonebot_plugin_waiter import prompt, suggest
from typing import TypedDict
from .config import plugin_config

driver = get_driver()

import nonebot_plugin_localstore as store  # noqa: E402

_CONFIG_DIR = store.get_config_dir("people_like")

_PROFILE = _CONFIG_DIR / "people_like_multi_group.json"

PROPERTIES: dict[str, dict[str, str]] = json.loads(
    "{}" if not _PROFILE.exists() else text if (text := _PROFILE.read_text()) is not None else "{}"
)

class PropConfig(TypedDict):
    range: str 
    type: str 
    default: str 

_EXPECT_PROP_NAMES: dict[str, PropConfig] = {
    "prompt": {"range": "", "type": "str", "default": ""},
    "topP": {"range": "", "type": "float", "default": "0.95"},
    "topK": {"range": "", "type": "int", "default": "40"},
    "temperature": {"range": "0.0-2.0", "type": "float", "default": "1.0"},
    "enableEnhancedCivicAnswers": {"range": "", "type": "bool", "default": "False"},
    "length": {"range": "", "type": "int", "default": "0"},
    "search": {"range": "", "type": "bool", "default": "False"},
    "reply_probability": {"range": "0.0-1.0", "type": "float", "default": str(plugin_config.reply_probability)},
    "at_reply_probability": {"range": "0.0-1.0", "type": "float", "default": str(plugin_config.reply_probability * 4)},
}

_BLACK_LIST_FILE = _CONFIG_DIR / "blacklist.json"

BLACK_LIST: list[str] = json.loads(
    "[]" if not _BLACK_LIST_FILE.exists() else text if (text := _BLACK_LIST_FILE.read_text()) is not None else "[]"
)


@on_command(cmd="block", permission=SUPERUSER, rule=to_me(), priority=1, block=True).handle()
async def block_group(bot: Bot, matcher: Matcher, e: MessageEvent):
    """通过指令拉黑群组"""
    global BLACK_LIST
    if not isinstance(e, GroupMessageEvent):
        group_list: list[str] = [str(group["group_id"]) for group in await bot.get_group_list()]
        resp = await suggest("请输入群号", timeout=60, expect=group_list)
        if not resp:
            await matcher.finish()
        if not str(resp).isdigit():
            await matcher.finish("输入无效，指令中断")
        group_id = str(resp)
    else:
        group_id = str(e.group_id)
    if group_id in BLACK_LIST:
        await matcher.finish("该群已在黑名单中")
    else:
        BLACK_LIST.append(group_id)
        await save_blacklist(matcher)
        await matcher.finish("该群已加入黑名单")


@on_command(cmd="unblock", permission=SUPERUSER, rule=to_me(), priority=1, block=True).handle()
async def unblock_group(bot: Bot, matcher: Matcher, e: MessageEvent):
    """通过指令解除拉黑群组"""
    global BLACK_LIST
    if not isinstance(e, GroupMessageEvent):
        group_list: list[str] = [str(group["group_id"]) for group in await bot.get_group_list()]
        resp = await suggest("请输入群号", timeout=60, expect=group_list)
        if not resp:
            await matcher.finish()
        if not str(resp).isdigit():
            await matcher.finish("输入无效，指令中断")
        group_id = str(resp)
    else:
        group_id = str(e.group_id)
    if group_id not in BLACK_LIST:
        await matcher.finish("该群未在黑名单中")
    else:
        BLACK_LIST.remove(group_id)
        await save_blacklist(matcher)
        await matcher.finish("该群已从黑名单中移除")


@on_command(cmd="bl", permission=SUPERUSER, rule=to_me(), priority=1, block=True).handle()
async def report_blacklist(bot: Bot, matcher: Matcher):
    """通过指令获取黑名单"""
    global BLACK_LIST
    if not BLACK_LIST:
        await matcher.finish("黑名单为空")
    else:
        block_list_txt = "\n".join(BLACK_LIST)
        await matcher.finish(f"黑名单\n{block_list_txt}")


def get_blacklist() -> list[str]:
    """获取黑名单"""
    global BLACK_LIST
    return BLACK_LIST


@on_command(cmd="gp", permission=SUPERUSER, rule=to_me(), priority=1, block=True).handle()
async def get_property(bot: Bot, matcher: Matcher, e: MessageEvent):
    """通过指令获取群组属性"""
    global PROPERTIES, _EXPECT_PROP_NAMES
    if not isinstance(e, GroupMessageEvent):
        # 获取所有群组
        group_list: list[str] = [str(group["group_id"]) for group in await bot.get_group_list()]
        resp = await suggest("请输入群号", timeout=60, expect=group_list)
        if not resp:
            await matcher.finish()
        if not str(resp).isdigit():
            await matcher.finish("输入无效，指令中断")
        group_id = str(resp)
    else:
        group_id = str(e.group_id)
    resp = await suggest("请选择要获取的属性名", timeout=60, expect=list(_EXPECT_PROP_NAMES.keys()))
    if not resp:
        await matcher.finish("操作超时，指令中断")
    property_name = str(resp).upper()
    conf = _EXPECT_PROP_NAMES.get(str(resp))
    if conf is None:
        await matcher.finish("属性名无效，指令中断")
    value = PROPERTIES.get(group_id, {}).get(property_name)
    ret = conf["default"] if value is None else value # type: ignore
    await matcher.finish(ret)


@on_command(cmd="sp", permission=SUPERUSER, rule=to_me(), priority=1, block=True).handle()
async def set_property(bot: Bot, matcher: Matcher, e: MessageEvent):
    """通过指令设置群组属性"""
    global PROPERTIES
    if not isinstance(e, GroupMessageEvent):
        # 获取所有群组
        group_list: list[str] = [str(group["group_id"]) for group in await bot.get_group_list()]
        resp = await suggest("请输入群号", timeout=60, expect=group_list)
        if not resp:
            await matcher.finish()
        if not str(resp).isdigit():
            await matcher.finish("输入无效，指令中断")
        group_id = str(resp)
    else:
        group_id = str(e.group_id)
    resp = await suggest("请选择要设置的属性名", timeout=60, expect=list(_EXPECT_PROP_NAMES.keys()))
    if not resp:
        await matcher.finish()
    property_name = str(resp).upper()
    conf = _EXPECT_PROP_NAMES.get(str(resp))
    if conf is None:
        await matcher.finish("属性名无效，指令中断")
    prompt_str = f"""请输入要设置的属性值（取消操作请输入cancel，重置输入reset）
键：{property_name}
{"范围：" + conf['range'] if conf['range'] else ""}
类型：{conf['type']}
默认值：{conf['default']}
    """
    resp = await prompt(prompt_str, timeout=60)
    if not resp:
        await matcher.finish()
    value = str(resp)
    if value.lower() == "reset":
        value = None
    elif value.lower() == "cancel":
        await matcher.finish("操作取消")
    # 赋值
    g_v = PROPERTIES.get(group_id, {})
    if value is None:
        g_v.pop(property_name, None)
        ret: str = f"""群：{group_id}
键：{property_name}
已删除"""
    else:
        g_v.update({property_name: value})
        ret: str = f"""群：{group_id}
键：{property_name}
值：{value}"""
    PROPERTIES.update({group_id: g_v})
    # 保存到文件
    await save_profile(matcher)
    await matcher.finish(ret)


def get_value_or_default(group_id: int, key: str, default: str = "") -> str:
    """获取群组属性"""
    global PROPERTIES
    return PROPERTIES.get(str(group_id), {}).get(key.upper(), default)


async def save_profile(matcher: Matcher):
    """保存配置文件"""
    global PROPERTIES, _PROFILE
    async with open(_PROFILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(PROPERTIES))
    await matcher.send("配置文件已保存")


async def save_blacklist(matcher: Matcher):
    """保存黑名单"""
    global BLACK_LIST, _BLACK_LIST_FILE
    async with open(_BLACK_LIST_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(BLACK_LIST))
    await matcher.send("黑名单已保存")
