from nonebot import require
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
    name="set_title",
    description="",
    usage="设置头衔",
)

st = on_alconna(
    Alconna(
        "头衔",
        Subcommand(
            "清空",
            Args["to?", At],
            alias={"清除", "删除", "剔除", "取消"},
        ),
        Subcommand(
            "设置",
            Args["to?", At],
            Args["title", str],
            alias={"修改", "改", "更", "更新"}
        ),
    ),
    response_self=True,
)


@st.assign("设置")
async def set_title(
    bot: Bot,
    event: GroupMessageEvent,
    to: Match[At],
    title: Match[str],
):
    interface = get_interface(bot)
    if interface is None:
        return
    if to.available:
        if str(event.user_id) in bot.config.superusers or str(event.user_id) == str(to.result.target):  # 如果是超级用户，则允许修改其他人头衔
            to_user = int(to.result.target)
            user = await interface.get_member(scene_type=SceneType.GROUP, scene_id=str(event.group_id), user_id=str(to_user))
            if user is None:
                return
            await bot.set_group_special_title(group_id=event.group_id, user_id=to_user, special_title=title.result)
            await UniMessage.text(f"已将{user.nick or user.user.name}的头衔修改为{title.result}").finish()
        else:
            await UniMessage.text("你没有权限修改他人头衔哦~").finish()
    else:
        await bot.set_group_special_title(group_id=event.group_id, user_id=event.user_id, special_title=title.result)
        await UniMessage.text(f"已将你的头衔修改为{title.result}").finish()


@st.assign("清空")
async def clear_title(bot: Bot, event: GroupMessageEvent, to: Match[At]):
    interface = get_interface(bot)
    if interface is None:
        return
    if to.available:
        if str(event.user_id) in bot.config.superusers or str(event.user_id) == str(to.result.target):  # 如果是超级用户，则允许修改其他人头衔
            to_user = int(to.result.target)
            user = await interface.get_member(scene_type=SceneType.GROUP, scene_id=str(event.group_id), user_id=str(to_user))
            if user is None:
                return
            await bot.set_group_special_title(group_id=event.group_id, user_id=to_user)
            await UniMessage.text(f"已将{user.nick or user.user.name}的头衔清空").finish()
        else:
            await UniMessage.text("你没有权限修改他人头衔哦~").finish()
    else:
        await bot.set_group_special_title(group_id=event.group_id, user_id=event.user_id)
        await UniMessage.text("已将你的头衔清空").finish()
