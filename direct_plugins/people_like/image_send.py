from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment, Bot as OB11Bot
import nonebot_plugin_localstore as store  # noqa: E402
from httpx import AsyncClient
from aiofiles import open as aopen

import os
from typing import Literal, Optional

from google.genai.types import (
    Part,
    GenerateContentConfig,
    SafetySetting,
    HarmCategory,
    HarmBlockThreshold,
    CreateCachedContentConfig,
)
from google import genai
from .config import plugin_config
from pydantic import BaseModel
import json

from nonebot_plugin_apscheduler import scheduler

os.environ["http_proxy"] = "http://127.0.0.1:7890/"
os.environ["https_proxy"] = "http://127.0.0.1:7890/"

_GEMINI_CLIENT = genai.Client(
    api_key=plugin_config.gemini_key,
    http_options={"api_version": "v1alpha", "timeout": 120_000, "headers": {"transport": "rest"}},
)

image_dir_path = store.get_data_dir("people_like") / "image"

_CONFIG_DIR = store.get_config_dir("people_like")

_CACHE_PROFILE = _CONFIG_DIR / "cache_profile.txt"


class ImageId(BaseModel):
    id: str
    """图片id
    """


async def get_file_name_of_image_will_sent(description: str, group_id: int):
    """根据描述信息获取最匹配的图片文件名

    Args:
        description (str): 描述信息
        group_id (int): 群号
    """
    global _GEMINI_CLIENT
    if _CACHE_PROFILE.exists():
        cached_content_name = _CACHE_PROFILE.read_text()
        if not cached_content_name:
            cached_content_name = await reset_cache()
    else:
        cached_content_name = await reset_cache()


    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-1.5-flash-8b",
        contents=description,
        config=GenerateContentConfig(
            cached_content=cached_content_name,
            response_mime_type="application/json",
            response_schema=ImageId,
            safety_settings=[
                SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, threshold=HarmBlockThreshold.OFF),
            ],
        ),
    )

    logger.debug(f"获取图片id成功，返回结果：{resp.text}")
    id = json.loads(str(resp.text))["id"]
    await send_image(id, group_id)


async def send_image(file_name: str, group_id: int):
    """根据文件名称发送图片"""
    bot = get_bot()
    logger.debug(f"发送图片{file_name}到群{group_id}")
    async with aopen(image_dir_path.joinpath(file_name), "rb") as f:
        content = await f.read()
    if isinstance(bot, OB11Bot):
        await bot.send_group_msg(group_id=group_id, message=Message(MessageSegment.image(content)))


async def inc_image(event: GroupMessageEvent) -> bool:
    """包含图片表情"""
    return event.message.has("image")


_HTTP_CLIENT = AsyncClient()


@on_message(rule=inc_image).handle()
async def add_image(event: GroupMessageEvent):
    if not image_dir_path.exists():
        image_dir_path.mkdir(parents=True)
    ms = event.message.include("image")
    image_ms = [m for m in ms if (s := m.data["summary"]) is not None and s != ""]
    for m in image_ms:
        url = m.data["url"]
        file_name = str(m.data.get("file"))
        resp = await _HTTP_CLIENT.get(url)
        async with aopen(image_dir_path.joinpath(file_name), "wb") as f:
            await f.write(resp.content)
        logger.info(f"下载图片{file_name}成功")



@scheduler.scheduled_job("cron", hour="0", id="reset_cache")
async def reset_cache() -> Optional[str]:
    """每天0点重置缓存"""
    global _CACHE_PROFILE
    # 发送图片缓存后重置缓存键名
    contents = []
    # 遍历图片，组成contents
    for _, _, files in os.walk(image_dir_path):
        for file in files:
            async with aopen(image_dir_path.joinpath(file), "rb") as f:
                content = await f.read()
                suffix_name = str(file).split(".")[-1]
                mime_type: Literal["image/jpeg", "image/gif", "image/png"] = "image/jpeg"
                match suffix_name:
                    case "jpg":
                        mime_type = "image/jpeg"
                    case "gif":
                        mime_type = "image/gif"
                    case "png":
                        mime_type = "image/png"
                # 将文件名作为id，以及图片二进制信息作为一条消息发送
                parts = [Part.from_text(text=f"id: {file}"), Part.from_bytes(data=content, mime_type=mime_type)]
                # 组合所有图片消息
                contents.append({"role": "user", "parts": parts})

    cached_content = _GEMINI_CLIENT.caches.create(
        model="gemini-1.5-flash-8b",
        config=CreateCachedContentConfig(
            contents=contents,
            system_instruction="根据给定的描述信息，从下面图片中选择一张最符合该描述信息的图片，返回其id",
            ttl=f"{48 * 60 * 60 - 1}s",  # 48小时 - 1秒过期
        ),
    )

    logger.debug(f"创建缓存成功，返回结果：{cached_content.name}")

    # 更新缓存键
    async with aopen(_CACHE_PROFILE, "w") as f:
        await f.write(str(cached_content.name))

    return cached_content.name
