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
from nonebot_plugin_alconna.uniseg import Text

__plugin_meta__ = PluginMetadata(
    name="set_title",
    description="",
    usage="设置头衔",
)

st = on_alconna(
    Alconna(
        "设置头衔",
        Args["to?", At],
        Args["title", Text],
    ),
    aliases={"指定头衔", "修改头衔", "头衔"},
    response_self=True,
)


@st.handle()
async def set_title(
    bot: Bot,
    event: GroupMessageEvent,
    to: Match[At],
    title: Match[Text],
):
    if to.available:
        if str(event.user_id) in bot.config.superusers:  # 如果是超级用户，则允许修改其他人头衔
            to_user = int(to.result.target)
            await bot.set_group_special_title(group_id=event.group_id, user_id=to_user, special_title=title.result.text)
            await UniMessage.text(f"已将{to_user}的头衔修改为{title.result}").finish()
        else:
            await UniMessage.text("你没有权限修改他人头衔哦~").finish()
    else:
        await bot.set_group_special_title(group_id=event.group_id, user_id=event.user_id, special_title=title.result.text)
        await UniMessage.text(f"已将你的头衔修改为{title.result}").finish()