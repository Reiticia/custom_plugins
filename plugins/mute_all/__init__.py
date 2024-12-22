from pathlib import Path
from nonebot import on_regex
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.permission import GROUP_MEMBER
from common.permission import admin_permission
from .config import Config, plugin_config


__plugin_meta__ = PluginMetadata(name="mute_all", description="", usage="", config=Config)


def gen_permission():
    if plugin_config.all:
        return admin_permission
    else:
        return GROUP_MEMBER


@on_regex(pattern="^(本群)?(开始|开启|打开|即刻)?戒严$", permission=gen_permission()).handle()
async def _(bot: Bot, event: GroupMessageEvent):
    path = Path(__file__).parent / "mute.jpg"
    mute_img = MessageSegment.image(path)
    await bot.send(event, mute_img)
    await bot.set_group_whole_ban(group_id=event.group_id, enable=True)


@on_regex(pattern="^(本群)?(解除|取消|关闭|停止)戒严$", permission=gen_permission()).handle()
async def _(bot: Bot, event: GroupMessageEvent):
    path = Path(__file__).parent / "unmute.jpg"
    mute_img = MessageSegment.image(path)
    await bot.send(event, mute_img)
    await bot.set_group_whole_ban(group_id=event.group_id, enable=False)
