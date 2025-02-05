from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment, Bot as OB11Bot
import nonebot_plugin_localstore as store  # noqa: E402
from httpx import AsyncClient
from aiofiles import open as aopen

import os
from typing import Literal

from google.genai.types import Part, GenerateContentConfig, SafetySetting, HarmCategory, HarmBlockThreshold
from google import genai
from .config import plugin_config
from pydantic import BaseModel
import json


_GEMINI_CLIENT = genai.Client(api_key=plugin_config.gemini_key, http_options={"api_version": "v1alpha"})

image_dir_path = store.get_data_dir("people_like") / "image"


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
    default_prompt = "根据给定的描述信息，从下面图片中选择一张最符合该描述信息的图片，返回其id"
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

    contents.append({"role": "user", "parts": [Part.from_text(text=description)]})

    if len(contents) == 0:
        return ""

    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=contents,
        config=GenerateContentConfig(
            system_instruction=default_prompt,
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
