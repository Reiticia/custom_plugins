from pathlib import Path
from nonebot import on_command, on_fullmatch
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from common.permission import admin_permission


__plugin_meta__ = PluginMetadata(
    name="mute_all",
    description="",
    usage="",
)


@on_fullmatch(msg="戒严", permission=admin_permission).handle()
async def _(bot: Bot, event: GroupMessageEvent):
    path = Path(__file__).parent / "mute.jpg"
    mute_img = MessageSegment.image(path)
    await bot.send(event, mute_img)
    await bot.set_group_whole_ban(group_id=event.group_id, enable=True)


@on_fullmatch(msg="取消戒严", permission=admin_permission).handle()
async def _(bot: Bot, event: GroupMessageEvent):
    path = Path(__file__).parent / "unmute.jpg"
    mute_img = MessageSegment.image(path)
    await bot.send(event, mute_img)
    await bot.set_group_whole_ban(group_id=event.group_id, enable=False)
