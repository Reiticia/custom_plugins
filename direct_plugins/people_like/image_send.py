from nonebot import get_bot, logger, on_message, get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, Bot as OB11Bot
import nonebot_plugin_localstore as store  # noqa: E402
from httpx import AsyncClient
from aiofiles import open as aopen

import os
from typing import Literal, Optional

from google.genai.types import (
    File,
    Part,
    GenerateContentConfig,
    SafetySetting,
    HarmCategory,
    HarmBlockThreshold,
    Content,
    ContentListUnion,
    UploadFileConfig,
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


class LocalFile(BaseModel):
    mime_type: Literal["image/jpeg", "image/png"]
    file_name: str
    file: File


_FILES: list[LocalFile] = []


class ImageName(BaseModel):
    name: str
    """图片名称
    """


async def get_file_name_of_image_will_sent(description: str, group_id: int) -> MessageSegment | None:
    """根据描述信息获取最匹配的图片文件名

    Args:
        description (str): 描述信息
        group_id (int): 群号
    """
    global _GEMINI_CLIENT
    prompt = "根据给定的描述信息，从下面图片中选择一张最符合该描述信息的图片，返回其图片名称"
    contents: ContentListUnion = [
        Content(
            role="user",
            parts=[
                Part.from_uri(file_uri=str(local_file.file.uri), mime_type=str(local_file.file.mime_type)),
                Part.from_text(
                    text=f"图片名称：{local_file.file_name}",
                ),
            ],
        )
        for local_file in _FILES
    ]

    contents.append(
        Content(
            role="user",
            parts=[
                Part.from_text(
                    text=description,
                )
            ],
        )
    )

    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=contents,
        config=GenerateContentConfig(
            system_instruction=prompt,
            response_mime_type="application/json",
            response_schema=ImageName,
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
    name = json.loads(str(resp.text))["name"]
    return await send_image(name, group_id)


async def send_image(file_name: str, group_id: int) -> MessageSegment | None:
    """根据文件名称发送图片"""
    bot = get_bot()
    logger.debug(f"发送图片{file_name}到群{group_id}")
    async with aopen(image_dir_path.joinpath(file_name), "rb") as f:
        content = await f.read()
    if isinstance(bot, OB11Bot):
        # await bot.send_group_msg(group_id=group_id, message=Message(MessageSegment.image(content)))
        return MessageSegment.image(content)
    else:
        return None


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
        # 文件不存在则写入
        if not (file_path := image_dir_path.joinpath(file_name)).exists():
            async with aopen(file_path, "wb") as f:
                await f.write(resp.content)
        logger.info(f"下载图片{file_name}成功")
        # 上传图片到gemini
        suffix_name = str(file_name).split(".")[-1]
        mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
        match suffix_name:
            case "jpg" | "gif":
                mime_type = "image/jpeg"
            case "png":
                mime_type = "image/png"
        file = await _GEMINI_CLIENT.aio.files.upload(file=file_path, config=UploadFileConfig(mime_type=mime_type))
        _FILES.append(LocalFile(mime_type=mime_type, file_name=file_name, file=file))


driver = get_driver()


inited = False


@driver.on_bot_connect
async def upload_image() -> Optional[str]:
    """每天0点重置缓存"""
    global inited
    if inited:
        return
    inited = True
    global _FILES, _GEMINI_CLIENT
    # 发送图片缓存后重置缓存键名
    files = []
    # 遍历图片，组成contents
    for _, _, files in os.walk(image_dir_path):
        for local_file in files:
            suffix_name = str(local_file).split(".")[-1]
            mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
            match suffix_name:
                case "jpg" | "gif":
                    mime_type = "image/jpeg"
                case "png":
                    mime_type = "image/png"
            file_path = image_dir_path / local_file
            file = await _GEMINI_CLIENT.aio.files.upload(file=file_path, config=UploadFileConfig(mime_type=mime_type))
            _FILES.append(LocalFile(mime_type=mime_type, file_name=local_file, file=file))
