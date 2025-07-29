from pathlib import Path
import random
import os
import asyncio
import json
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel
from httpx import AsyncClient
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
from moviepy import VideoFileClip
import tempfile

from google.genai.types import (
    Part,
    GenerateContentConfig,
    SafetySetting,
    HarmCategory,
    HarmBlockThreshold,
    Content,
    ContentListUnion,
)

from .model import ImageSender
from .setting import get_value_or_default
from .vector import _GEMINI_CLIENT, VectorDataImage, get_text_embedding, get_milvus_vector_client, analysis_image_to_str_description


EMOJI_DIR_PATH = store.get_data_dir("people_like") / "image"
NORMAL_IMAGE_DIR_PATH = store.get_data_dir("people_like") / "normal"


_IMAGE_DICT: dict[str, ImageSender] = {}


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
    global _GEMINI_CLIENT, _IMAGE_DICT
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
            file_name = str(im.data["file"])
            bytes_content = await get_file_bytes(file_name, file_url=im.data["url"])
            mime_type = get_mime_type(file_name)
            if bytes_content:
                parts.append(Part.from_bytes(data=bytes_content, mime_type=mime_type))
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
            file_name = str(im.data["file"])
            byte_content = await get_file_bytes(file_name, file_url=im.data["url"])
            mime_type = get_mime_type(file_name)
            if byte_content:
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
                mime_type = get_mime_type(file_name)
                if emoji_id:
                    mime_type = "image/png"
                suffix_name = str(file_name).split(".")[-1]
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
                            file_size=file_size,
                            key=key,
                            emoji_id=emoji_id,
                            emoji_package_id=emoji_package_id,
                            create_time=int(event.time),
                            update_time=int(event.time),
                            mime_type=mime_type
                        )
                        session.add(image_sender)
                        logger.info(f"新增表情包图片{file_name}成功")

                        parts = []
                        parts.append(Part.from_text(text=f"分析一下{'这段视频' if mime_type.startswith('video') else '这张图片'}描述的内容，用中文描述它"))
                        bytes_content = await get_file_bytes(file_name, file_url=url)
                        if bytes_content:
                            parts.append(Part.from_bytes(data=bytes_content, mime_type=mime_type))
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
                                    "group_id": event.group_id,
                                    "user_id": event.user_id,
                                    "summary": summary,
                                    "url": url,
                                    "file_size": file_size,
                                    "key": key,
                                    "emoji_id": emoji_id,
                                    "emoji_package_id": emoji_package_id,
                                    "mime_type": mime_type                             
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

@driver.on_bot_connect
@scheduler.scheduled_job("interval", minutes=10, id="update_image_dict_cache")
async def refresh_image_cache():
    global _IMAGE_DICT
    # 查数据库里所有的动画表情
    async with get_session() as session:
        res = await session.scalars(select(ImageSender))
    res = list(res)
    _IMAGE_DICT = {i.name:i for i in res}



who_send = on_command("谁发的", aliases={"谁发的图片", "图片来源"})


@who_send.handle()
async def who_send_image(msg: Message = CommandArg()):
    img_name = msg.extract_plain_text()
    if not img_name:
        await who_send.finish("请指定图片名称")

    async with get_session() as session:
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
    async with get_session() as session:
        res = await session.execute(select(ImageSender))
        all = res.scalars().fetchall()
        await count_image.send(str(len(all)))


def get_mime_type(filename: str) -> Literal["image/jpeg", "image/png", "video/mp4"]:
    ext = filename.lower().split(".")[-1]
    match ext:
        case "png":
            return "image/png"
        case "gif":
            return "video/mp4"
        case _:
            return "image/jpeg"



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
            # 文件后缀是 gif 时，mime_type 必须是 video/mp4，否则删除原文件重新分析图片
            if res[0].name.endswith('gif') and mime_type != "video/mp4" and res[0].emoji_id is None: # type: ignore
                logger.info(f"图片{name}已存在，但mime_type不正确，删除原分析数据，重新分析图片")
                # 删除原分析数据
                await milvus_client.delete_image_data(name)
            elif res[0].emoji_id is not None and res[0].mime_type != "image/png":  # type: ignore
                logger.info(f"图片{name}已存在，但mime_type不正确，删除原分析数据，重新分析图片")
                # 删除原分析数据
                await milvus_client.delete_image_data(name)
            else:
                skip_count += 1
                logger.debug(f"图片{name}已存在，不进行数据迁移")
                continue

        try:
            mime_type = get_mime_type(name)
            if emoji_id is not None and len(emoji_id) > 0:
                mime_type = "image/png"
            byte_content = await get_file_bytes(name, file_path=EMOJI_DIR_PATH.joinpath(name))
            parts = []
            parts.append(Part.from_text(text=f"请用中文描述分析一下{'这段视频' if mime_type.startswith('video') else '这张图片'}的内容"))
            if byte_content:
                parts.append(Part.from_bytes(data=byte_content, mime_type=mime_type))
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
            logger.error(f"数据{name}迁移失败{repr(e)}")

    else:
        # 删除失败的文件以及本地文件
        if fail_files:
            for file_name in fail_files:
                file_path = EMOJI_DIR_PATH.joinpath(file_name)
                if file_path.exists():
                    os.remove(file_path)
                    logger.info(f"删除失败的文件{file_name}成功")
                else:
                    logger.warning(f"文件{file_name}不存在，无法删除")

        async with get_session() as session:
            count = await session.execute(delete(ImageSender).where(ImageSender.name.in_(fail_files)))
            await session.commit()
        logger.info(f"删除数据库中{count.rowcount}条迁移失败的数据")
        logger.info(f"{skip_count}条数据跳过迁移，{error_count}条数据迁移失败，{success_count}条数据迁移成功")


async def get_file_bytes(file_name: str, *, file_url: Optional[str] = None, file_path: Optional[Path] = None) -> Optional[bytes]:
    """获取文件二进制数据"""
    ext = file_name.split(".")[-1]
    bytes_content = None
    if file_url is not None:
        resp = await _HTTP_CLIENT.get(file_url)
        bytes_content = resp.content
    if file_path is not None:
        async with aopen(file_path, "rb") as f:
            bytes_content = await f.read()
    if ext in ["jpg", "jpeg", "png"]:
        return bytes_content
    if ext == "gif" and bytes_content:
        # GIF 文件需要处理成 MP4 格式文件并重新获取 bytes
        return await gif_bytes_to_mp4_bytes(bytes_content)
    return None


async def gif_bytes_to_mp4_bytes(gif_bytes: bytes) -> bytes:
    """从GIF二进制数据转换为MP4二进制数据"""
    def _convert():
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix='.gif', delete=False) as temp_gif:
            temp_gif.write(gif_bytes)
            temp_gif_path = temp_gif.name
        
        # 创建临时输出文件
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_mp4:
            temp_mp4_path = temp_mp4.name
        
        try:
            clip = VideoFileClip(temp_gif_path)
            
            # 直接写入临时文件，添加更多参数
            clip.write_videofile(
                temp_mp4_path,
                codec='libx264',
                audio_codec='aac',
                logger=None,
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                ffmpeg_params=['-pix_fmt', 'yuv420p']  # 确保兼容性
            )
            
            clip.close()
            
            # 读取生成的MP4文件
            with open(temp_mp4_path, 'rb') as f:
                content = f.read()
            
            return content
        except Exception as e:
            logger.error(f"GIF转MP4失败: {e}")
            # 如果转换失败，返回原始GIF数据
            return gif_bytes
        finally:
            # 清理临时文件
            if os.path.exists(temp_gif_path):
                os.unlink(temp_gif_path)
            if os.path.exists(temp_mp4_path):
                os.unlink(temp_mp4_path)
    
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _convert)