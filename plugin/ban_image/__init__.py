from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot import on_message
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, Message, Bot, GROUP_OWNER, GROUP_ADMIN
from nonebot.adapters.onebot.v11.event import Reply
from typing import Optional
from .algorithm import check_image_equals, ban_iamge_size, save

from nonebot.matcher import Matcher

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="ban_image",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)


permit_roles = GROUP_OWNER | SUPERUSER | GROUP_ADMIN
"""允许执行命令的角色
"""

async def check_img(event: GroupMessageEvent):
    """判断是否违禁图片"""
    img_message = event.get_message().include("image")
    if len(img_message) == 0:
        return False
    if any(await check_image_equals(msg) for msg in img_message):
        return True
    return False


@on_message(rule=check_img).handle()
async def ban_img_sender(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """违禁图片禁言"""
    await bot.delete_msg(message_id=event.message_id)
    await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=60)
    await matcher.finish(" 听不懂人话？不是叫你别发了吗？", at_sender=True)


async def check_message_add(event: GroupMessageEvent):
    """检测消息合法性"""
    global ban_iamge_size
    cmd_msg = [msg.data.get("text", "").strip() for msg in event.get_message() if msg.type == "text"]
    if "别发了" in cmd_msg:
        reply_msg: Optional[Reply] = event.reply
        if reply_msg and len(imgs := reply_msg.message.include("image")) > 0:
            # 添加到违禁图片列表
            ban_iamge_size |= {int(img.data.get("file_size")) for img in imgs}
            await save(ban_iamge_size)
            return True
    return False


@on_message(rule=check_message_add, permission=permit_roles).handle()
async def add_ban_image(event: GroupMessageEvent, matcher: Matcher):
    """添加违禁图片"""
    reply_msg: Optional[Reply] = event.reply
    reply_user_id = reply_msg.sender.user_id
    message = Message([MessageSegment.at(reply_user_id), MessageSegment.text(" 别再发这张表情了")])
    await matcher.finish(message=message)


async def check_message_del(event: GroupMessageEvent):
    """检测消息合法性"""
    global ban_iamge_size
    cmd_msg = [msg.data.get("text", "").strip() for msg in event.get_message() if msg.type == "text"]
    if "发吧发吧" in cmd_msg:
        reply_msg: Optional[Reply] = event.reply
        if reply_msg and len(imgs := reply_msg.message.include("image")) > 0:
            # 删除指定违禁图片
            ban_iamge_size -= {int(img.data.get("file_size")) for img in imgs}
            await save(ban_iamge_size)
            return True
    return False


@on_message(rule=check_message_del, permission=permit_roles).handle()
async def remove_ban_image(matcher: Matcher): 
    message = Message([MessageSegment.text("随便你们了，发吧发吧")])
    await matcher.finish(message=message)
