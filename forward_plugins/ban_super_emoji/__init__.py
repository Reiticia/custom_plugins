from nonebot import get_plugin_config, on_message
from nonebot.params import Depends
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule
from pathlib import Path

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="ban_super_emoji",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)


super_emojis_files = Path(__file__).parent / "super_emojis.txt"


emojis = {s.split(" ")[0]: s.split(" ")[1] for s in super_emojis_files.read_text(encoding="utf-8").splitlines()}


def _is_super_emoji(event: GroupMessageEvent) -> bool:
    message = event.get_message()

    if len(ms := message.include("face")) == 1:
        id = ms[0].data["id"]
        if str(id) in emojis:
            return True
    return False


def _emoji_name(event: GroupMessageEvent) -> str:
    message = event.get_message()

    if len(ms := message.include("face")) == 1:
        id = ms[0].data["id"]
        return emojis.get(str(id), "")
    return ""


@on_message(
    rule=Rule(_is_super_emoji),
).handle()
async def _(bot: Bot, event: GroupMessageEvent, emoji_name: str = Depends(_emoji_name)):
    if emoji_name:
        await bot.delete_msg(message_id=event.message_id)
        await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=60)
        await bot.send(event=event, message=f"禁止发送{emoji_name}表情")
