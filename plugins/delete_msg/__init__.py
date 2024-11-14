from nonebot import get_plugin_config, on_fullmatch
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="delete_msg",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

delete_msg = on_fullmatch(msg=("删一下，谢谢", "delete, plz"))


@delete_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    reply = event.reply
    if reply:
        await bot.delete_msg(message_id=reply.message_id)
        await bot.delete_msg(message_id=event.message_id)
        await delete_msg.finish("已对所有群成员使用记忆消除术")
    else:
        await delete_msg.finish("你好歹告诉我删啥吧")
