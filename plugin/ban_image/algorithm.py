from pathlib import Path
from nonebot.adapters.onebot.v11 import MessageSegment
from aiofiles import open as aopen
from json import loads, dumps
from nonebot import require

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402

ban_iamge_size: set[int] = {}

ban_iamge_size_file: Path = store.get_data_file("ban_image", "ban_iamge_size.json")


# 读取持久化的数据
if ban_iamge_size_file.exists():
    ban_iamge_size = loads(t) if (t := ban_iamge_size_file.read_text()) else {}


async def save(ban_iamge_size: set[int] = {}):
    """保存禁图数据
    """
    async with aopen(ban_iamge_size_file, mode="w") as fp:
        await fp.write(dumps(ban_iamge_size, indent=4))


async def check_image_equals(img: MessageSegment) -> bool:
    """检测是否匹配 TODO 更好的匹配策略
    
    Args:
        img (MessageSegment): 图片消息段

    Return:
        bool: 是否匹配
    """
    return int(img.data.get("file_size")) in ban_iamge_size