import random
import time
import os
import asyncio
import typing_extensions
import json
import aiofiles
import io
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel
from httpx import RemoteProtocolError, AsyncClient
from aiofiles import open as aopen
from nonebot_plugin_orm import get_session
from sqlalchemy import delete, select, update
from nonebot import get_bot, logger, on_command, on_message, get_driver
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, MessageSegment, Bot as OB11Bot
from nonebot.adapters.onebot.utils import b2s, f2s
from nonebot.permission import SUPERUSER
import nonebot_plugin_localstore as store  # noqa: E402
from nonebot_plugin_apscheduler import scheduler
from pathlib import Path

from PIL import Image, ImageSequence


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

from .model import ImageSender
from .setting import get_value_or_default
from .vector import _GEMINI_CLIENT, VectorDataImage, get_text_embedding, get_milvus_vector_client, analysis_image_to_str_description


EMOJI_DIR_PATH = store.get_data_dir("people_like") / "image"
NORMAL_IMAGE_DIR_PATH = store.get_data_dir("people_like") / "normal"


_IMAGE_DICT: dict[str, ImageSender] = {}


class LocalFile(BaseModel):
    mime_type: Literal["image/jpeg", "image/png"]
    file_name: str
    file: File


# _FILES: list[LocalFile] = []

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

async def get_file_name_of_image_will_sent_by_description_vec(description: str, group_id: int) -> MessageSegment | None:
    """根据描述信息的向量值获取最匹配的图片文件名

    Args:
        description (str): 描述信息
        group_id (int): 群号
    """
    global _GEMINI_CLIENT
    # 先查数据库里所有的动画表情
    milvus_client = await get_milvus_vector_client()
    vec_data = await get_text_embedding(description)
    search_data_result: list[VectorDataImage] = await milvus_client.search_image_data([vec_data], file_id=True, search_len=10)
    file_ids = [item.name for item in search_data_result if item.name is not None]
    logger.debug(f"群聊 {group_id} 获取图片id，返回结果：{file_ids}")
    if search_data_result:
        for _ in range(len(file_ids)):
            random_image = random.choice(search_data_result)
            if random_image:
                name = random_image.name
                logger.info(f"群聊 {group_id} 获取图片id成功，返回结果：{name}")
                try:
                    # 读取图片二进制
                    async with aopen(EMOJI_DIR_PATH.joinpath(str(name)), "rb") as f:
                        content = await f.read()
                        parts = [Part.from_bytes(data=content, mime_type=str(random_image.mime_type))]
                        res = await analysis_image_trait(parts, group_id)
                        if res.is_adult or res.is_violence:
                            logger.info(f"图片{name}包含违禁内容, 已删除，重新选取图片")
                            os.remove(EMOJI_DIR_PATH.joinpath(str(name)))
                            search_data_result.remove(random_image)
                            continue
                        if not res.is_japan_anime and get_value_or_default(group_id, "anime_only", False):
                            logger.info(f"图片{name}不是二次元图片，不予展示，重新选取图片")
                            search_data_result.remove(random_image)
                            continue
                        return await send_image(str(name), group_id, ext_data_vec=random_image)
                except Exception as e:
                    search_data_result.remove(random_image)
                    logger.info(f"群聊 {group_id} 发送图片{name}失败，重新选取图片，失败原因: {repr(e)}")



async def send_image(file_name: str, group_id: int, ext_data: Optional[ImageSender] = None, ext_data_vec: Optional[VectorDataImage] = None) -> MessageSegment | None:
    """根据文件名称发送图片"""
    bot = get_bot()
    logger.debug(f"发送图片{file_name}到群{group_id}")
    async with aopen(EMOJI_DIR_PATH.joinpath(file_name), "rb") as f:
        content = await f.read()
    if isinstance(bot, OB11Bot):
        if ext_data is not None:
            if ext_data.key is None:
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
                        "emoji_id": ext_data.emoji_id,
                        "emoji_package_id": ext_data.emoji_package_id,
                        "key": ext_data.key,
                        "summary": ext_data.summary,
                    },
                )
        elif ext_data_vec is not None:
            if ext_data_vec.key is None:
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
                        "emoji_id": ext_data_vec.emoji_id,
                        "emoji_package_id": ext_data_vec.emoji_package_id,
                        "key": ext_data_vec.key,
                        "summary": ext_data_vec.summary,
                    },
                )
        else:
            async with get_session() as session:
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


async def analysis_image_trait(file_part: list[Part], group_id: int = 0) -> AnalysisResult:
    """分析图片是否包含违禁内容"""

    global _GEMINI_CLIENT
    prompt = "根据给出的图片内容，判断是否含有色情内容，暴力内容或日本动漫形象内容，返回指定数据类型"
    file_part.append(Part.from_text(text="分析图片是否包含色情内容，暴力内容或日本动漫形象内容"))
    contents: ContentListUnion = [Content(role="user", parts=file_part)]
    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.5-flash-lite",
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
            mime_type = get_mime_type(file_name)
            parts.append(Part.from_bytes(data=byte_content, mime_type=mime_type))
        res = await analysis_image_trait(parts)
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
            mime_type = get_mime_type(file_name)
            parts.append(Part.from_bytes(data=byte_content, mime_type=mime_type))
        res = await analysis_image_trait(parts)
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


_HTTP_CLIENT = AsyncClient(verify=False, timeout=30.0)


@on_message(rule=inc_image).handle()
async def add_image(event: GroupMessageEvent):
    if not EMOJI_DIR_PATH.exists():
        EMOJI_DIR_PATH.mkdir(parents=True)
    if not NORMAL_IMAGE_DIR_PATH.exists():
        NORMAL_IMAGE_DIR_PATH.mkdir(parents=True)
    ms = event.message.include("image")
    for m in ms:
        url = m.data["url"]
        file_name = str(m.data.get("file"))
        if (s := m.data["summary"]) is not None and s != "" and ((st := m.data.get("sub_type")) is None or st != 0):
            summary = m.data["summary"]
            file_size = m.data.get("file_size")
            key = m.data.get("key")
            emoji_id = m.data.get("emoji_id")
            emoji_package_id = m.data.get("emoji_package_id")
            resp = await _HTTP_CLIENT.get(url)
            # 文件不存在则写入
            if not (file_path := EMOJI_DIR_PATH.joinpath(file_name)).exists():
                async with aopen(file_path, "wb") as f:
                    await f.write(resp.content)
                logger.info(f"下载表情包图片{file_name}成功")
                # 上传图片到gemini
                mime_type = get_mime_type(file_name)
                suffix_name = str(file_name).split(".")[-1]
                file = await _GEMINI_CLIENT.aio.files.upload(
                    file=file_path, config=UploadFileConfig(mime_type=mime_type)
                )
                # 插入数据库
                async with get_session() as session:
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
                            remote_file_name=file.name,
                            mime_type=mime_type
                        )
                        session.add(image_sender)
                        logger.info(f"新增表情包图片{file_name}成功")

                        parts = [Part.from_text(text="Summarize the content of the following set of pictures, using multiple tags to describe them, at least 40 tags")]
                        parts.extend(await process_image_file(EMOJI_DIR_PATH.joinpath(file_name)))
                        content = await analysis_image_to_str_description(parts=parts)
                        vec = await get_text_embedding(content)

                        image_vec_data = VectorDataImage(
                            description=content,
                            name=file_name,
                            summary=summary,
                            mime_type=mime_type,
                            file_size=file_size,
                            key=str(key),
                            emoji_id=str(emoji_id),
                            emoji_package_id=str(emoji_package_id),
                            vec=vec,
                        )

                        milvus_client = await get_milvus_vector_client()
                        await milvus_client.insert_image_data([image_vec_data])
                        logger.info(f"插入图片向量数据到Milvus成功，图片名称：{file_name}")

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
                                    "mime_type": mime_type,
                                    "remote_file_name": file.name,                                    
                                }
                            )
                        )

                        logger.info(f"更新表情包图片{file_name}成功")
                    await session.commit()

        else:
            resp = await _HTTP_CLIENT.get(url)
            # 文件不存在则写入
            if not (file_path := NORMAL_IMAGE_DIR_PATH.joinpath(file_name)).exists():
                async with aopen(file_path, "wb") as f:
                    await f.write(resp.content)
                logger.info(f"下载图片{file_name}成功")


driver = get_driver()


# @driver.on_bot_connect
# @scheduler.scheduled_job("interval", minutes=10, id="update_image_dict_cache")
@typing_extensions.deprecated("")
async def refresh_image_cache():
    global _IMAGE_DICT
    # 查数据库里所有的动画表情
    async with get_session() as session:
        res = await session.scalars(select(ImageSender))
    res = list(res)
    _IMAGE_DICT = {i.name:i for i in res}


def get_mime_type(filename: str) -> Literal["image/jpeg", "image/png"]:
    ext = filename.lower().split(".")[-1]
    return "image/png" if ext == "png" else "image/jpeg"



@driver.on_bot_connect
async def migrate_imagesender_to_milvus():
    async with get_session() as session:
        res = list(await session.scalars(select(ImageSender)))
    
    logger.debug(f"共需要迁移{len(res)}条数据")
    milvus_client = await get_milvus_vector_client()
    skip_count = 0
    success_count = 0
    error_count = 0
    fail_files = []
    for i in res:
        name = i.name
        summary = i.summary
        mime_type = i.mime_type
        file_size = i.file_size
        key = i.key
        emoji_id = i.emoji_id
        emoji_package_id = i.emoji_package_id

        res = await milvus_client.query_image_data(name)
        if len(res) > 0:
            # 判断描述中是否含有中文，有则删除原来的记录，重新设置
            description = res[0].description
            if description and any('\u4e00' <= ch <= '\u9fff' for ch in description):
                # 删除原有记录，重新迁移
                await milvus_client.delete_image_data(name)
                logger.info(f"图片{name}描述不合法，已删除原有记录，准备重新迁移")
            else:
                skip_count += 1
                logger.debug(f"图片{name}已存在且描述无中文，不进行数据迁移")
                continue

        mime_type = get_mime_type(name)
        try:
            parts = [Part.from_text(text="Summarize the content of the following set of pictures, using multiple tags to describe them, at least 40 tags")]
            parts.extend(await process_image_file(EMOJI_DIR_PATH.joinpath(name)))
            description = await analysis_image_to_str_description(parts=parts)
            vec = await get_text_embedding(description)
            vec_image_data = VectorDataImage(
                description=description,
                name=name,
                summary=summary,
                mime_type=mime_type,
                file_size=file_size,
                key=key,
                emoji_id=emoji_id,
                emoji_package_id=emoji_package_id,
                vec=vec
            )

            await milvus_client.insert_image_data([vec_image_data])
            success_count += 1
            logger.info(f"数据{name}迁移成功")
        except Exception as e:
            fail_files.append(name)
            error_count += 1
            logger.error(f"数据{name}, mime_type为{mime_type}，迁移失败{repr(e)}")

    else:
        # 删除失败的文件以及本地文件
        # if fail_files:
        #     for file_name in fail_files:
        #         file_path = EMOJI_DIR_PATH.joinpath(file_name)
        #         if file_path.exists():
        #             os.remove(file_path)
        #             logger.info(f"删除失败的文件{file_name}成功")
        #         else:
        #             logger.warning(f"文件{file_name}不存在，无法删除")
            
        # async with get_session() as session:
            # count = await session.execute(delete(ImageSender).where(ImageSender.name.in_(fail_files)))
            # await session.commit()
        # logger.info(f"删除数据库中{count.rowcount}条迁移失败的数据")
        logger.info(f"{skip_count}条数据跳过迁移，{error_count}条数据迁移失败，{success_count}条数据迁移成功")



async def process_image_file(file_path: Path) -> list[Part]:
    """处理即将发送给AI进行分析的图片输入，如果是静态图片，则直接去二进制内容，如果是动态图片，则分帧去多次二进制内容"""
    parts = []
    mime_type = get_mime_type(file_path.name)
    if file_path.name.endswith(".gif"):
        frame_paths = await split_gif_pillow_async(file_path, file_path.name)
        for path in frame_paths:
            async with aopen(path, "rb") as f:
                content = await f.read()
            parts.append(Part.from_bytes(data=content, mime_type=mime_type))
        await remove_gif_frames(file_path)
    else:
        async with aopen(file_path, "rb") as f:
            content = await f.read()
        parts.append(Part.from_bytes(data=content, mime_type=mime_type))
    return parts


async def async_save_image(image: Image.Image, path: Path):
    """Pillow保存为字节流，然后异步写入文件"""
    buf = io.BytesIO()
    rgb_image = image.convert("RGB")
    rgb_image.save(buf, format="JPEG")
    async with aiofiles.open(path, "wb") as f:
        await f.write(buf.getvalue())

GIF_FRAME_OUTPUT_DIR = store.get_cache_dir("people_like") / "gif_frames"

async def split_gif_pillow_async(gif_path: Path, file_name: str) -> list[Path]:
    """将gif动态图片分割成多个静态图片"""
    gif = Image.open(gif_path)
    GIF_FRAME_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGBA", gif.size, (0, 0, 0, 0))
    durations = []
    tasks = []
    frame_paths = []
    file_name = file_name.split(".")[0]

    for i, frame in enumerate(ImageSequence.Iterator(gif)):
        rgba = frame.convert("RGBA")
        composed = Image.alpha_composite(canvas, rgba)
        save_path = GIF_FRAME_OUTPUT_DIR / f"{file_name}_frame_{i:03d}.png"
        tasks.append(async_save_image(composed, save_path))
        canvas = composed
        durations.append(int(frame.info.get("duration", 0)))
        frame_paths.append(save_path)

    await asyncio.gather(*tasks)

    logger.info(f"完成，共导出 {len(durations)} 帧")
    return frame_paths


async def remove_gif_frames(file_path: Path):
    """删除 GIF 动画帧"""
    file_name = file_path.name.split(".")[0]

    for frame in GIF_FRAME_OUTPUT_DIR.glob(f"{file_name}_frame_*.png"):
        frame.unlink(missing_ok=True)
    logger.info(f"删除 {file_name} GIF 动画帧成功")
