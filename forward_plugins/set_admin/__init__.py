from nonebot import get_plugin_config, on_command, require
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

require("nonebot_plugin_alconna")

from nonebot_plugin_alconna import (
    AlcMatches,
    Alconna,
    Args,
    Arparma,
    At,
    Image,
    Match,
    Hyper,
    Option,
    Subcommand,
    Text,
    UniMessage,
    MultiVar,
    AlconnaMatches,
    UniMsg,
    on_alconna,
)

__plugin_meta__ = PluginMetadata(
    name="set_admin",
    description="",
    usage="设置管理员",
)

sa = on_alconna(
    Alconna(
        "管理",
        Subcommand("+", Args["to?", At], alias={"添加", "设置"}),
        Subcommand("-", Args["to?", At], alias={"移除", "取消"}),
    ),
    aliases={"管理员"},
    response_self=True,
)


@sa.assign("+")
async def set_title(bot: Bot, event: GroupMessageEvent, to: Match[At]):
    if str(event.user_id) in bot.config.superusers:  # 如果是超级用户，则允许设置管理员
        await bot.set_group_admin(group_id=event.group_id, user_id=int(to.result.target), enable=True)
    else:
        await UniMessage.text("你没有权限设置管理员哦~").finish()


@sa.assign("-")
async def clear_title(bot: Bot, event: GroupMessageEvent, to: Match[At]):
    if str(event.user_id) in bot.config.superusers:  # 如果是超级用户，则允许设置管理员
        await bot.set_group_admin(group_id=event.group_id, user_id=int(to.result.target), enable=False)
    else:
        await UniMessage.text("你没有权限取消管理员哦~").finish()
