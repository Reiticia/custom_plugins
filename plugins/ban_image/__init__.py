from nonebot import logger, on_fullmatch
from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, Message, Bot
from nonebot.adapters.onebot.v11.event import Reply
from typing import Optional
from nonebot.matcher import Matcher
from .struct import BanImage
from nonebot.params import Depends
from common.struct import ExpirableDict
from common.permission import admin_permission
from .metadata import __plugin_meta__ as __plugin_meta__
from nonebot import require

require("nonebot_plugin_localstore")
require("nonebot_plugin_orm")
require("nonebot_plugin_uninfo")

ban_images: dict[int, BanImage] = {}

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
        ban_images.update({group_id: (ban_image := await BanImage(group_id).load())})
        return ban_image


mute_dict: dict[int, ExpirableDict[str, int]] = {}
"""分群组存储禁言字典"""


async def check_img(event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    """判断是否违禁图片"""
    img_message = event.get_message().include("image")
    if len(img_message) == 0:
        return False
    if any(ban_image.check_image_equals(msg) for msg in img_message):
        return True
    return False


async def compute_mute_time(event: GroupMessageEvent) -> int:
    """计算禁言时间"""
    global mute_dict
    user_id = event.user_id
    group_id = event.group_id
    # 判断这个成员是否于指定时间段内被禁言过，如果是，则加大处罚力度
    mute_dict_group = mute_dict.get(group_id, ExpirableDict(str(group_id)))
    key = str(user_id)
    time = 1 if (t := mute_dict_group.get(key)) is None else t << 1
    logger.debug(f"ttl: {mute_dict_group.ttl(key)}s")
    mute_dict_group.set(key, time, ttl=time * 2 * 60)
    mute_dict.update({
        group_id: mute_dict_group
    })
    return time


@on_message(rule=check_img).handle()
async def ban_img_sender(bot: Bot, event: GroupMessageEvent, matcher: Matcher, time:int = Depends(compute_mute_time)):
    """违禁图片禁言"""
    user_id = event.user_id
    group_id = event.group_id
    await bot.delete_msg(message_id=event.message_id)
    await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=time * 60)
    await matcher.finish(" 听不懂人话？不是叫你别发了吗？", at_sender=True)


async def check_message_add(
    event: GroupMessageEvent,
):
    """检测消息合法性"""
    cmd_msg = [msg.data.get("text", "").strip() for msg in event.get_message() if msg.type == "text"]
    if "别发了" in cmd_msg:
        reply_msg: Optional[Reply] = event.reply
        if reply_msg and len(reply_msg.message.include("image")) > 0:
            return True
    return False


@on_message(rule=check_message_add, permission=admin_permission).handle()
async def add_ban_image(event: GroupMessageEvent, matcher: Matcher, ban_image: BanImage = Depends(get_ban_image)):
    """添加违禁图片"""
    reply_msg: Optional[Reply] = event.reply
    if reply_msg :
        reply_user_id = reply_msg.sender.user_id
        imgs = reply_msg.message.include("image")
        # 添加到违禁图片列表
        await ban_image.add_ban_image(imgs)
        message = Message([MessageSegment.at(str(reply_user_id)), MessageSegment.text(" 别再发这表情了")])
        await matcher.finish(message=message)


async def check_message_del(event: GroupMessageEvent):
    """检测消息合法性"""
    cmd_msg = [msg.data.get("text", "").strip() for msg in event.get_message() if msg.type == "text"]
    if "随便发" in cmd_msg:
        reply_msg: Optional[Reply] = event.reply
        if reply_msg and len(reply_msg.message.include("image")) > 0:
            return True
    return False


@on_message(rule=check_message_del, permission=admin_permission).handle()
async def remove_ban_image(event: GroupMessageEvent, matcher: Matcher, ban_image: BanImage = Depends(get_ban_image)):
    reply_msg: Optional[Reply] = event.reply
    if reply_msg :
        imgs = reply_msg.message.include("image")
        # 删除指定违禁图片
        fail_list = await ban_image.remove_ban_image(imgs)
        if len(fail_list) > 0:
            message = Message([MessageSegment.text("部分图片删除失败")])
        else:
            message = Message([MessageSegment.text("随便你们了，发吧发吧")])
        await matcher.finish(message=message)


@on_fullmatch(msg="让我看看什么不能发").handle()
async def list_ban_images(bot: Bot, event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    message = await ban_image.list_ban_image("bot", int(bot.self_id))
    if len(message) > 0:
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=message,
        )
    else:
        await bot.send_group_msg(group_id=event.group_id, message="当前没有违禁图片")


@on_fullmatch(msg="都可以发", permission=admin_permission).handle()
async def rm_all_ban_images(bot: Bot, event: GroupMessageEvent, ban_image: BanImage = Depends(get_ban_image)):
    await ban_image.clear_ban_image()
    await bot.send_group_msg(group_id=event.group_id, message="已清空违禁图片")
