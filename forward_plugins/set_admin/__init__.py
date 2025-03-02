from nonebot import require
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

require("nonebot_plugin_alconna")
require("nonebot_plugin_uninfo")

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    At,
    Match,
    Subcommand,
    UniMessage,
    on_alconna,
)

from nonebot_plugin_uninfo import SceneType, get_interface

__plugin_meta__ = PluginMetadata(
    name="set_admin",
    description="",
    usage="设置管理员",
)

sa = on_alconna(
    Alconna(
        "管理",
        Subcommand("+", Args["to", At], alias={"添加", "设置"}, help_text="设置管理员"),
        Subcommand("-", Args["to", At], alias={"移除", "取消"}, help_text="取消管理员"),
    ),
    aliases={"管理员"},
    response_self=True
)


@sa.assign("+")
async def set_title(bot: Bot, event: GroupMessageEvent, to: Match[At]):
    interface = get_interface(bot)
    if interface is None:
        return
    if str(event.user_id) in bot.config.superusers:  # 如果是超级用户，则允许设置管理员
        await bot.set_group_admin(group_id=event.group_id, user_id=int(to.result.target), enable=True)
        user = await interface.get_member(scene_type=SceneType.GROUP, scene_id=str(event.group_id), user_id=str(to.result.target))
        if user is None:
            return
        await UniMessage.text(f"已将{user.nick or user.user.name}设置为管理员").finish()
    else:
        await UniMessage.text("你没有权限设置管理员哦~").finish()


@sa.assign("-")
async def clear_title(bot: Bot, event: GroupMessageEvent, to: Match[At]):
    interface = get_interface(bot)
    if interface is None:
        return
    if str(event.user_id) in bot.config.superusers:  # 如果是超级用户，则允许设置管理员
        await bot.set_group_admin(group_id=event.group_id, user_id=int(to.result.target), enable=False)
        user = await interface.get_member(scene_type=SceneType.GROUP, scene_id=str(event.group_id), user_id=str(to.result.target))
        if user is None:
            return
        await UniMessage.text(f"已将{user.nick or user.user.name}管理员取消").finish()
    else:
        await UniMessage.text("你没有权限取消管理员哦~").finish()
