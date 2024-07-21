from pathlib import Path
from nonebot import get_plugin_config, on_command, require
from nonebot.plugin import PluginMetadata
from nonebot import on_message
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, Message, Bot, GROUP_OWNER, GROUP_ADMIN
from nonebot.adapters.onebot.v11.event import Reply
from typing import Optional

from nonebot.matcher import Matcher

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="ban_image",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)


require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402

ban_iamge_size: list[int] = []


permit_roles = GROUP_OWNER | SUPERUSER | GROUP_ADMIN
"""允许执行命令的角色
"""

ban_iamge_size_file: Path = store.get_data_file("ban_image", "ban_iamge_size.json")

def check_img(event: GroupMessageEvent):
    """判断是否违禁图片

    Args:
        event (GroupMessageEvent): _description_

    Returns:
        _type_: _description_
    """
    img_message = event.get_message().include("image")
    if len(img_message) == 0:
        return False
    if any(int(msg.data.get('file_size')) in ban_iamge_size for msg in img_message):
        return True
    return False

@on_message(rule=check_img).handle()
async def ban_img_sender(bot: Bot, event: GroupMessageEvent, matcher: Matcher): 
    await bot.delete_msg(message_id=event.message_id)
    await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=60)
    await matcher.finish(" 听不懂人话？不是叫你别发了吗？", at_sender=True)
    

async def check_message(event: GroupMessageEvent):
    """检测消息合法性

    Args:
        event (GroupMessageEvent): _description_
    """
    cmd_msg = [msg.data.get("text","").strip() for msg in event.get_message() if msg.type == 'text']
    if "别发了" in cmd_msg:  
        reply_msg:Optional[Reply] = event.reply
        if reply_msg and len(imgs := reply_msg.message.include("image")) > 0:
            # 添加到违禁图片列表
            ban_iamge_size.extend([int(img.data.get('file_size')) for img in imgs])  
            return True
    return False


@on_message(rule=check_message, permission=permit_roles).handle()
async def add_ban_image(event: GroupMessageEvent, matcher: Matcher):
    """添加违禁图片

    Args:
        event (GroupMessageEvent): _description_
        matcher (Matcher): _description_
    """
    print("match")
    reply_msg:Optional[Reply] = event.reply
    reply_user_id = reply_msg.sender.user_id
    message = Message([MessageSegment.at(reply_user_id), MessageSegment.text(" 别再发这张表情了")])
    await matcher.finish(message=message)