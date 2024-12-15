from pathlib import Path
from nonebot import on_command, require
from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, Message, MessageSegment
from nonebot.adapters.onebot.v11.event import Reply
from typing import Optional

from nonebot.matcher import Matcher


require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402


ban_iamge_size_file: Path = store.get_data_file("ban_image", "ban_iamge_size.json")


@on_command(cmd="1111").handle()
async def download_img(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """添加违禁图片

    Args:
        event (GroupMessageEvent): _description_
        matcher (Matcher): _description_
    """
    print("match")
    reply_msg: Optional[Reply] = event.reply
    if reply_msg and len(imgs := reply_msg.message.include("image")) > 0:
        # 添加到违禁图片列表
        for img in imgs:
            for key, value in img.data.items():
                print(f"{key}--{value}")


@on_message().handle()
async def _(e: GroupMessageEvent):
    for msg in e.message.include("json"):
        print("=============")
        print(msg.data)
        print("=============")
