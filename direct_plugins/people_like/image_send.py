import time
from datetime import datetime
from nonebot import get_bot, logger, on_command, on_message, get_driver
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, MessageSegment, Bot as OB11Bot
from nonebot.adapters.onebot.utils import b2s, f2s
from nonebot.permission import SUPERUSER
import nonebot_plugin_localstore as store  # noqa: E402
from httpx import AsyncClient
from aiofiles import open as aopen
from nonebot_plugin_orm import get_session
from sqlalchemy import select, update
from .model import ImageSender

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

from google.genai.errors import ClientError

from .setting import get_value_or_default
from .config import plugin_config
from pydantic import BaseModel
import json
from httpx import RemoteProtocolError

from nonebot_plugin_apscheduler import scheduler

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

SAFETY_SETTINGS = [
    SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.OFF),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.OFF),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.OFF),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.OFF),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, threshold=HarmBlockThreshold.OFF),
]


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

    model = get_value_or_default(group_id, "model", "gemini-2.0-flash")

    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model=model,
        contents=contents,
        config=GenerateContentConfig(
            system_instruction=prompt,
            response_mime_type="application/json",
            response_schema=ImageName,
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    name = json.loads(str(resp.text))["name"]
    logger.info(f"群聊 {group_id} 获取图片id成功，返回结果：{name}")
    parts = [
        Part.from_uri(file_uri=str(local_file.file.uri), mime_type=str(local_file.file.mime_type))
        for local_file in _FILES
        if local_file.file_name == name
    ]
    res = await analysis_image(parts, group_id)
    if res.is_adult or res.is_violence:
        logger.info(f"图片{name}包含违禁内容, 已删除")
        os.remove(image_dir_path.joinpath(name))
        return None
    elif not res.is_japan_anime and bool(get_value_or_default(group_id, "anime_only")):
        logger.info(f"图片{name}不是二次元图片，不予展示")
        return None
    else:
        return await send_image(name, group_id)


async def send_image(file_name: str, group_id: int) -> MessageSegment | None:
    """根据文件名称发送图片"""
    bot = get_bot()
    logger.debug(f"发送图片{file_name}到群{group_id}")
    async with aopen(image_dir_path.joinpath(file_name), "rb") as f:
        content = await f.read()
    if isinstance(bot, OB11Bot):
        # TODO 查询数据库中指定名称的文件，判断其是否为商店表情
        session = get_session()
        async with session.begin():
            res = await session.execute(select(ImageSender).where(ImageSender.name == file_name))
            first = res.scalars().first()
            if first is None:
                return None
            if first.key is None:
                return MessageSegment(
                    "image",
                    {
                        "file": f2s(content),
                        "sub_type": str(1),
                        "cache": b2s(True),
                        "proxy": b2s(True),
                    },
                )
            else:
                return MessageSegment(
                    "mface",
                    {
                        "emoji_id": first.emoji_id,
                        "emoji_package_id": first.emoji_package_id,
                        "key": first.key,
                        "summary": first.summary,
                    },
                )
    else:
        return None


class AnalysisResult(BaseModel):
    """图片分析结果"""

    is_adult: bool
    """色情内容"""
    is_violence: bool
    """暴力内容"""
    is_japan_anime: bool
    """是否为日本卡通动漫角色"""


async def analysis_image(file_part: list[Part], group_id: int = 0) -> AnalysisResult:
    """分析图片是否包含违禁内容"""

    model = get_value_or_default(group_id, "model", "gemini-2.0-flash")

    global _GEMINI_CLIENT
    prompt = "根据给出的图片内容，判断是否含有色情内容，暴力内容或日本动漫形象内容，返回指定数据类型"
    file_part.append(Part.from_text(text="分析图片是否包含色情内容，暴力内容或日本动漫形象内容"))
    contents: ContentListUnion = [Content(role="user", parts=file_part)]
    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model=model,
        contents=contents,
        config=GenerateContentConfig(
            system_instruction=prompt,
            response_mime_type="application/json",
            response_schema=AnalysisResult,
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    logger.debug(f"分析图片成功，返回结果：{resp.text}")
    r = AnalysisResult(**json.loads(str(resp.text)))
    return r


anti_image = on_command("ani", aliases={"图片分析", "图片审查", "分析图片", "审查图片"})


@anti_image.handle()
async def anti(e: MessageEvent):
    """分析图片"""
    if not e.message.has("image") and e.reply is None:
        return
    if ims := e.message.include("image"):
        parts = []
        for im in ims:
            resp = await _HTTP_CLIENT.get(im.data["url"])
            byte_content = resp.read()
            file_name = str(im.data["file"])
            suffix_name = str(file_name).split(".")[-1]
            mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
            match suffix_name:
                case "jpg" | "gif":
                    mime_type = "image/jpeg"
                case "png":
                    mime_type = "image/png"
            parts.append(Part.from_bytes(data=byte_content, mime_type=mime_type))
        res = await analysis_image(parts)
        if res.is_adult:
            await anti_image.send("图片包含色情内容")
        if res.is_violence:
            await anti_image.send("图片包含暴力内容")
        if res.is_japan_anime:
            await anti_image.send("图片包含二次元内容")

        await anti_image.finish(f"图片分析结束{res}")

    if e.reply is not None:
        ims = e.reply.message.include("image")
        parts = []
        for im in ims:
            resp = await _HTTP_CLIENT.get(im.data["url"])
            byte_content = resp.read()
            file_name = str(im.data["file"])
            suffix_name = str(file_name).split(".")[-1]
            mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
            match suffix_name:
                case "jpg" | "gif":
                    mime_type = "image/jpeg"
                case "png":
                    mime_type = "image/png"
            parts.append(Part.from_bytes(data=byte_content, mime_type=mime_type))
        res = await analysis_image(parts)
        if res.is_adult:
            await anti_image.send("图片包含色情内容")
        if res.is_violence:
            await anti_image.send("图片包含暴力内容")
        if res.is_japan_anime:
            await anti_image.send("图片包含二次元内容")

        await anti_image.finish(f"图片分析结束{res}")


async def inc_image(event: GroupMessageEvent) -> bool:
    """包含图片表情"""
    return event.message.has("image")


_HTTP_CLIENT = AsyncClient()


@on_message(rule=inc_image, priority=10).handle()
async def add_image(event: GroupMessageEvent):
    if not image_dir_path.exists():
        image_dir_path.mkdir(parents=True)
    ms = event.message.include("image")
    image_ms = [
        m
        for m in ms
        if (s := m.data["summary"]) is not None and s != "" and ((st := m.data.get("sub_type")) is None or st != 0)
    ]
    for m in image_ms:
        url = m.data["url"]
        summary = m.data["summary"]
        file_size = m.data.get("file_size")
        key = m.data.get("key")
        emoji_id = m.data.get("emoji_id")
        emoji_package_id = m.data.get("emoji_package_id")
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
            # 插入数据库
            session = get_session()
            async with session.begin():
                res = await session.execute(select(ImageSender).where(ImageSender.name == file_name))
                first = res.scalars().first()
                if first is None:  # 如果原来不存在，则插入
                    image_sender = ImageSender(
                        name=file_name,
                        summary=summary,
                        group_id=event.group_id,
                        user_id=event.user_id,
                        ext_name=suffix_name,
                        url=url,
                        file_uri=str(file.uri),
                        file_size=file_size,
                        key=key,
                        emoji_id=emoji_id,
                        emoji_package_id=emoji_package_id,
                        create_time=int(event.time),
                        update_time=int(event.time),
                    )
                    session.add(image_sender)
                    await session.commit()
                    logger.info(f"新增图片{file_name}成功")
                else:  # 如果原来存在，则更新
                    await session.execute(
                        update(ImageSender)
                        .where(ImageSender.name == file_name)
                        .values(
                            {
                                "update_time": int(event.time),
                                "file_uri": str(file.uri),
                                "group_id": event.group_id,
                                "user_id": event.user_id,
                                "summary": summary,
                                "url": url,
                                "file_size": file_size,
                                "key": key,
                                "emoji_id": emoji_id,
                                "emoji_package_id": emoji_package_id,
                            }
                        )
                    )
                    logger.info(f"更新图片{file_name}成功")


driver = get_driver()


@driver.on_bot_connect
@scheduler.scheduled_job("interval", days=2, id="my_job_id")
async def upload_image() -> Optional[str]:
    """每搁两天重置图片文件缓存"""
    global _FILES, _GEMINI_CLIENT
    image_list = await _GEMINI_CLIENT.aio.files.list()
    async for file in image_list:
        if n := file.name:
            await _GEMINI_CLIENT.aio.files.delete(name=n)
    # 重置缓存键名
    _FILES = []
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
            need_upload = True
            search_session = get_session()
            async with search_session.begin():
                res = await search_session.execute(select(ImageSender).where(ImageSender.name == local_file))
                first = res.scalars().first()
                now = int(time.time())
                if first is not None:  # 如果原来存在，则更新
                    if (
                        now - int(first.update_time) < 36 * 60 * 60
                        and first.remote_file_name is not None
                    ):
                        remote_file_name = f"files/{first.remote_file_name}"
                        try:
                            exsit_file = await _GEMINI_CLIENT.aio.files.get(name=remote_file_name)
                            if exsit_file is not None:
                                _FILES.append(LocalFile(mime_type=mime_type, file_name=local_file, file=exsit_file))
                                logger.info(f"图片: {local_file} 文件名: {remote_file_name} 未过期，跳过上传")
                                need_upload = False
                        except ClientError as e:
                            logger.error(f"{e.message}")


            if need_upload:
                # 图片即将过期，或者图片名未设置，则更新图片
                file_path = image_dir_path / local_file
                try:
                    file = await _GEMINI_CLIENT.aio.files.upload(
                        file=file_path, config=UploadFileConfig(mime_type=mime_type)
                    )
                    _FILES.append(LocalFile(mime_type=mime_type, file_name=local_file, file=file))
                    update_session = get_session()
                    async with update_session.begin():
                        await update_session.execute(
                            update(ImageSender)
                            .where(ImageSender.name == local_file)
                            .values(
                                {
                                    "update_time": int(time.time()),
                                    "file_uri": str(file.uri),
                                    "remote_file_name": str(file.name),
                                }
                            )
                        )
                        logger.info(f"更新图片{local_file}成功")
                except RemoteProtocolError as e:
                    logger.error(f"文件{file_path}上传失败{repr(e)}")


who_send = on_command("谁发的", aliases={"谁发的图片", "图片来源"})


@who_send.handle()
async def who_send_image(msg: Message = CommandArg()):
    img_name = msg.extract_plain_text()
    if not img_name:
        await who_send.finish("请指定图片名称")

    session = get_session()
    async with session.begin():
        res = await session.execute(select(ImageSender).where(ImageSender.name == img_name))
        first = res.scalars().first()
        if first is None:
            await who_send.finish("图片不存在")
        else:
            time = datetime.fromtimestamp(first.update_time).strftime("%Y-%m-%d %H:%M:%S")
            size = first.file_size
            emoji_id = first.emoji_id
            emoji_package_id = first.emoji_package_id
            message = f"""
来自群{first.group_id}的成员{first.user_id}
上传时间: {time}
大小: {size}
emoji_id: {emoji_id}
emoji_package_id: {emoji_package_id}
"""
            await who_send.finish(message.strip())


count_image = on_command("图片统计", aliases={"图片数量", "图片总数"}, permission=SUPERUSER)


@count_image.handle()
async def count_image_handle():
    session = get_session()
    async with session.begin():
        res = await session.execute(select(ImageSender))
        all = res.scalars().fetchall()
        await count_image.send(str(len(all)))
