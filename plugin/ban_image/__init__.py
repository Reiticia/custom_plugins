from nonebot import get_plugin_config, on_fullmatch
from nonebot.plugin import PluginMetadata
from nonebot import on_message
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, Message, Bot, GROUP_OWNER, GROUP_ADMIN
from nonebot.adapters.onebot.v11.event import Reply
from typing import Optional
from nonebot.matcher import Matcher
from .config import Config
from .struct import BanImage
from nonebot.params import Depends

ban_images: dict[int, BanImage] = {}

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


async def get_ban_image(event: GroupMessageEvent) -> BanImage:
    """子依赖 获取对应群组的BanImage信息

    Args:
        event (GroupMessageEvent): 群组消息事件

    Returns:
        BanImage: 违禁图片
    """
    global ban_images
    if (ban_image := ban_images.get(group_id := event.group_id)) is not None:
        return ban_image
    else:
        ban_images.update({
            group_id: (ban_image := await BanImage(group_id).load())
        })
        return ban_image


async def check_img(event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    """判断是否违禁图片"""
    img_message = event.get_message().include("image")
    if len(img_message) == 0:
        return False
    if any(ban_image.check_image_equals(msg) for msg in img_message):
        return True
    return False


@on_message(rule=check_img).handle()
async def ban_img_sender(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """违禁图片禁言"""
    await bot.delete_msg(message_id=event.message_id)
    user_id = event.user_id
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=60)
    await matcher.finish(" 听不懂人话？不是叫你别发了吗？", at_sender=True)


async def check_message_add(event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    """检测消息合法性"""
    cmd_msg = [msg.data.get("text", "").strip() for msg in event.get_message() if msg.type == "text"]
    if "别发了" in cmd_msg:
        reply_msg: Optional[Reply] = event.reply
        if reply_msg and len(imgs := reply_msg.message.include("image")) > 0:
            # 添加到违禁图片列表
            await ban_image.add_ban_image([img for img in imgs])
            return True
    return False


@on_message(rule=check_message_add, permission=permit_roles).handle()
async def add_ban_image(event: GroupMessageEvent, matcher: Matcher):
    """添加违禁图片"""
    reply_msg: Optional[Reply] = event.reply
    reply_user_id = reply_msg.sender.user_id
    message = Message([MessageSegment.at(reply_user_id), MessageSegment.text(" 别再发这张表情了")])
    await matcher.finish(message=message)


async def check_message_del(event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    """检测消息合法性"""
    cmd_msg = [msg.data.get("text", "").strip() for msg in event.get_message() if msg.type == "text"]
    if "随便发" in cmd_msg:
        reply_msg: Optional[Reply] = event.reply
        if reply_msg and len(imgs := reply_msg.message.include("image")) > 0:
            # 删除指定违禁图片
            await ban_image.remove_ban_image([img for img in imgs])
            return True
    return False


@on_message(rule=check_message_del, permission=permit_roles).handle()
async def remove_ban_image(matcher: Matcher):
    message = Message([MessageSegment.text("随便你们了，发吧发吧")])
    await matcher.finish(message=message)


@on_fullmatch(msg="让我看看什么不能发").handle()
async def list_ban_images(bot: Bot, event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    message = await ban_image.list_ban_image("bot", bot.self_id)
    if len(message) > 0:
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=message,
        )
    else:
        await bot.send_group_msg(group_id=event.group_id, message="当前没有违禁图片")
