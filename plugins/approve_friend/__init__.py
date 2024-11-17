from nonebot import get_plugin_config, on
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import FriendRequestEvent, Bot

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="approve_friend",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)


@on(type="request.friend").handle()
async def _(bot: Bot, e: FriendRequestEvent):
    await e.approve(bot=bot)
    for user in bot.config.superusers:
        if user == bot.self_id:
            continue
        await bot.send_private_msg(user_id=int(user), message=f"已同意{e.user_id}的好友请求")
