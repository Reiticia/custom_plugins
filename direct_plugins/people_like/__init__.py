from datetime import datetime, timedelta
import logging
import random
import re
import time
import json
import aiofiles
from httpx import AsyncClient
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from asyncio import sleep
from typing import Any, Literal, Optional
from pydantic import BaseModel
from nonebot import get_bot, logger, on_keyword, on_message, require, get_driver, on

from nonebot.rule import to_me
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, Message, MessageSegment
from google.genai.types import (
    Part,
    Tool,
    GenerateContentConfig,
    GoogleSearch,
    ToolListUnion,
    FunctionDeclaration,
    Schema,
    Type,
    ToolConfig,
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    HttpOptions,
    UrlContext,
    ThinkingConfig,
)
from google.genai.errors import APIError

from common import retry_on_exception
from common.struct import ExpirableDict

require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_orm")

from nonebot_plugin_waiter import Matcher
from nonebot_plugin_orm import get_session
from nonebot_plugin_apscheduler import scheduler

import nonebot_plugin_localstore as store

from sqlalchemy import delete, select, func
from .setting import get_value_or_default, get_blacklist
from .config import Config, plugin_config
from .image_send import get_file_name_of_image_will_sent_by_description_vec, SAFETY_SETTINGS
from .vector import (
    _GEMINI_CLIENT,
    analysis_image_to_str_description,
)
from .model import GroupMsg
from .task import get_model, change_model
from collections import defaultdict

__plugin_meta__ = PluginMetadata(
    name="people-like",
    description="",
    usage="",
    config=Config,
)

DRIVER = get_driver()


@scheduler.scheduled_job("interval", days=1, id="remove_old_msg")
async def _():
    async with get_session() as session:
        # 删除超过 7 天的消息
        seven_days_ago = int(time.time()) - 60 * 60 * 24 * 7
        result = await session.execute(delete(GroupMsg).where(GroupMsg.time < seven_days_ago))
        await session.commit()
        deleted_count = result.rowcount if result.rowcount is not None else 0
        logger.info(f"已删除超过7天的消息，共 {deleted_count} 条")


class Character(Enum):
    BOT = 1
    USER = 2


@dataclass
class ChatMsg:
    sender: Character
    content: list[Part]


@dataclass
class GroupMemberDict:
    group_id: int
    members: dict[int, str]

    def add_member(self, user_id: int, user_name: str):
        self.members[user_id] = user_name

    def get_id_by_name(self, user_name: str) -> Optional[int]:
        for user_id, name in self.members.items():
            if name == user_name:
                return user_id
        return None


GROUP_SPEAK_DISABLE: dict[int, bool] = {}

shutup = on_keyword(keywords={"闭嘴", "shut up", "shutup", "Shut Up", "Shut up", "滚", "一边去"}, rule=to_me())


EMOJI_ID_DICT: dict[int, str] = {}
EMOJI_NAME_DICT: dict[str, int] = {}


@DRIVER.on_startup
async def init_emoji_dict():
    """初始化表情字典"""
    logger.info("正在加载表情字典...")
    global EMOJI_ID_DICT, EMOJI_NAME_DICT
    if not EMOJI_ID_DICT:
        EMOJI_ID_DICT = load_emoji_txt_to_dict()
        EMOJI_NAME_DICT = {v: k for k, v in EMOJI_ID_DICT.items()}
        logger.info(f"已加载表情字典，共有 {len(EMOJI_ID_DICT)} 个表情")


def load_emoji_txt_to_dict(path: Path = Path(__file__).parent / "emoji.txt") -> dict[int, str]:
    emoji_dict: dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or " " not in line:
                continue
            parts = line.split(maxsplit=1)
            try:
                emoji_id = int(parts[0])
                desc = parts[1].strip()
                if desc:
                    emoji_dict[emoji_id] = desc
            except ValueError:
                continue  # 跳过非数字 id 的行
    return emoji_dict


@shutup.handle()
async def _(event: GroupMessageEvent):
    global GROUP_SPEAK_DISABLE
    gid = event.group_id
    GROUP_SPEAK_DISABLE.update({gid: True})
    await sleep(300)
    GROUP_SPEAK_DISABLE.update({gid: False})


on_msg: type[Matcher] = on_message()


@on_msg.handle()
async def receive_group_msg(bot: Bot, event: GroupMessageEvent) -> None:
    global GROUP_SPEAK_DISABLE
    # 群组id
    gid = event.group_id
    group_remark = await get_bot_nickname_of_group(gid)
    nickname = list(bot.config.nickname)[0] if len(group_remark) > 5 else group_remark
    # 黑名单内，不检查
    if str(gid) in get_blacklist():
        logger.warning(f"群{gid}消息黑名单内，不处理")
        return
    em = event.message
    # 8位及以上数字字母组合为无意义消息，可能为密码或邀请码之类，过滤不做处理
    if re.match(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$", em.extract_plain_text()):
        return
    await store_message_segment_into_db(event)

    logger.debug(f"receive: {em}")

    # 触发复读
    if (
        random.random() < plugin_config.repeat_probability
        and not GROUP_SPEAK_DISABLE.get(gid, False)
        and event.user_id != event.self_id
    ):
        logger.info(f"群{gid}触发复读")
        # 过滤掉图片消息，留下meme消息，mface消息，text消息
        new_message: Message = Message()
        for ms in em:
            if ms.type == "image" and ms.__dict__.get("summary") == "":
                # 图片消息，不处理
                continue
            if ms.type == "voice" or ms.type == "video":
                # 语音、视频消息，不处理
                continue
            if ms.type == "json":
                # json消息，不处理
                continue
            new_message.append(ms)
        if len(new_message) == 0 or new_message.extract_plain_text() == "":
            return
        await on_msg.finish(new_message)

    is_superuser = str(event.user_id) in DRIVER.config.superusers

    # 触发回复
    # 规则：
    # 1. 该群聊没有被闭嘴
    # 2. 满足回复时的概率 plugin_config.reply_probability
    # 3. 如果是提及机器人的消息 则回复概率为原回复概率 plugin_config.reply_probability 的 4 倍

    if (
        (
            (send := ((r := random.random()) < get_value_or_default(gid, "reply_probability")))
            or (event.is_tome() and (r < get_value_or_default(gid, "at_reply_probability") or send))
        )
        and not GROUP_SPEAK_DISABLE.get(gid, False)
        and event.user_id != event.self_id
    ):
        logger.info(f"reply: {em}")
        await chat_with_gemini(
            event.message_id, gid, nickname, await get_bot_gender(), await is_bot_admin(gid), is_superuser
        )


def convert_to_group_message_event(event: Event) -> GroupMessageEvent:
    """转换为群消息事件"""
    model = event.model_dump()
    model["post_type"] = "message"
    return GroupMessageEvent(**model)


on_self_msg = on("message_sent", priority=5)


@on_self_msg.handle()
async def receive_group_self_msg(raw_event: Event) -> None:
    """处理机器人自己发的消息"""
    if raw_event.model_dump()["message_type"] == "group":
        event = convert_to_group_message_event(raw_event)
        await store_message_segment_into_db(event)


async def sleep_sometime(size: int):
    """根据字数休眠一段时间"""
    time = random.random() * plugin_config.one_word_max_used_time_of_second * size
    await sleep(time)


_HTTP_CLIENT = AsyncClient()

ALL_IMAGE_FILE_CACHE_DIR = store.get_cache_dir("people_like") / "all"


async def store_message_segment_into_db(event: GroupMessageEvent):
    """提取群消息事件中的消息内容"""
    global _HTTP_CLIENT, ALL_IMAGE_FILE_CACHE_DIR
    em = event.message
    gid = event.group_id
    sender_user_id = event.user_id
    self_msg = event.self_id == event.user_id
    target: list[Part] = []
    file_ids: list[str] = []
    sender_nickname = await get_user_nickname_of_group(gid, int(sender_user_id))

    for ms in em:
        match ms.type:
            case "text":
                text = ms.data["text"]
                if len(target) > 0:
                    part = target.pop()
                    if txt := part.text:
                        target.append(Part.from_text(text=f"{txt}{text}"))
                    else:
                        target.append(Part.from_text(text=text))
                        file_ids.append("")
                else:
                    target.append(Part.from_text(text=text))
                    file_ids.append("")
            case "at":
                if len(target) > 0:
                    part = target.pop()
                    if txt := part.text:
                        target.append(Part.from_text(text=f"{txt}@{ms.data['qq']} "))
                    else:
                        target.append(Part.from_text(text=f"@{ms.data['qq']} "))
                        file_ids.append("")
                else:
                    target.append(Part.from_text(text=f"@{ms.data['qq']} "))
                    file_ids.append("")
            case "face":
                face_text = EMOJI_ID_DICT.get(ms.data["id"])
                face_text = "" if face_text is None else f"[/{face_text}]"
                if len(target) > 0:
                    part = target.pop()
                    if txt := part.text:
                        target.append(Part.from_text(text=f"{txt}{face_text} "))
                    else:
                        target.append(Part.from_text(text=f"{face_text} "))
                        file_ids.append("")
                else:
                    target.append(Part.from_text(text=f"{face_text} "))
                    file_ids.append("")
            case "image":
                if plugin_config.image_analyze:
                    # 下载图片进行处理
                    data = await _HTTP_CLIENT.get(ms.data["url"])
                    file_id = str(ms.data["file"])
                    file_ids.append(file_id)
                    # 写入本地路径 ALL_IMAGE_DIR / file_id
                    file_path = ALL_IMAGE_FILE_CACHE_DIR / file_id
                    file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
                    async with aiofiles.open(file_path, "wb") as f:
                        await f.write(data.content)

                    suffix_name = file_id.split(".")[-1]
                    mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
                    match suffix_name:
                        case "jpg" | "gif":
                            mime_type = "image/jpeg"
                        case "png":
                            mime_type = "image/png"
                    if data.status_code == 200:
                        target.append(Part.from_bytes(data=data.content, mime_type=mime_type))
            case _:
                pass

    # 新增数据到数据库
    message_id = event.message_id
    group_id = event.group_id
    user_id = event.user_id
    vector_data = []
    for index, part in enumerate(target):
        file_id = file_ids[index] if index < len(file_ids) else ""
        if part.text:
            vector_data.append(
                {
                    "message_id": message_id,
                    "group_id": group_id,
                    "user_id": user_id,
                    "self_msg": self_msg,
                    "to_me": event.is_tome(),
                    "index": index,
                    "nick_name": sender_nickname,
                    "content": part.text,
                    "file_id": file_id,
                    "time": int(time.time()),
                }
            )
        if part.inline_data:
            # 如果是图片，则先分析图片
            parts = []
            parts.append(Part.from_text(text="分析一下这张图片描述的内容，用中文描述它"))
            parts.append(part)
            content = await analysis_image_to_str_description(parts=parts)
            logger.debug(f"anaylysis iamge {file_id}")
            logger.debug(content)
            if content:
                vector_data.append(
                    {
                        "message_id": message_id,
                        "group_id": group_id,
                        "user_id": user_id,
                        "self_msg": self_msg,
                        "to_me": event.is_tome(),
                        "index": index,
                        "nick_name": sender_nickname,
                        "content": content,
                        "file_id": file_id,
                        "time": int(time.time()),
                    }
                )
    # 插入数据到数据库
    msg_data_list = []
    for data in vector_data:
        msg_data_list.append(GroupMsg(**data))
    async with get_session() as session:
        session.add_all(msg_data_list)
        await session.commit()


_USER_OF_GROUP_NICKNAME: dict[int, ExpirableDict[int, str]] = dict()
_BOT_OF_GROUP_NICKNAME: ExpirableDict[int, str] = ExpirableDict("bot_of_group_nickname")


async def get_user_nickname_of_group(group_id: int, user_id: int) -> str:
    """读取程序内存中缓存的用户在指定群组的昵称"""
    global _USER_OF_GROUP_NICKNAME
    gd = _USER_OF_GROUP_NICKNAME.get(group_id, ExpirableDict(str(group_id)))
    name = gd.get(user_id)
    if name is None:
        bot = get_bot()
        try:
            info: dict[str, Any] = dict(await bot.call_api("get_group_member_info", group_id=group_id, user_id=user_id))
        except Exception as e:
            logger.error("获取群成员信息失败", str(e))
            info: dict[str, Any] = {}
        nickname_obj = info.get("card")
        if not nickname_obj:
            nickname_obj = info.get("nickname")
        nickname: str = str(nickname_obj)
        # 缓存一天
        gd.set(user_id, nickname, 60 * 60 * 24)
        _USER_OF_GROUP_NICKNAME.update({group_id: gd})
        return nickname
    else:
        return name


async def get_bot_nickname_of_group(group_id: int) -> str:
    """读取程序内存中缓存的Bot在指定群组的昵称"""
    global _BOT_OF_GROUP_NICKNAME
    name = _BOT_OF_GROUP_NICKNAME.get(group_id)
    if name is None:
        bot = get_bot()
        info: dict[str, Any] = dict(
            await bot.call_api("get_group_member_info", group_id=group_id, user_id=int(bot.self_id))
        )
        nickname: str = str(info.get("card", info.get("nickname", str(info.get("user_id")))))
        # 缓存一天
        _BOT_OF_GROUP_NICKNAME.set(group_id, nickname, 60 * 60 * 24)
        return nickname
    else:
        return name


_BOT_INFO: ExpirableDict[int, dict[str, Any]] = ExpirableDict("bot_info")


async def get_bot_gender() -> Optional[str]:
    """获取机器人号性别"""
    global _BOT_INFO
    bot = get_bot()
    if isinstance(bot, Bot):
        bot_id = int(bot.self_id)
        info = _BOT_INFO.get(bot_id)
        if info is None:
            new_info: dict[str, Any] = dict(await bot.call_api("get_stranger_info", user_id=bot_id))
            # 缓存一天
            _BOT_INFO.set(bot_id, new_info, 60 * 60 * 24)
            # 看看拿到的 sex 字段是什么数据
            if sex := new_info.get("sex"):
                match sex:
                    case "male":
                        return "男"
                    case "female":
                        return "女"
            else:
                return None
        else:
            if sex := info.get("sex"):
                match sex:
                    case "male":
                        return "男"
                    case "female":
                        return "女"
            else:
                return None
    else:
        return None


_BOT_PERMISSION: ExpirableDict[int, bool] = ExpirableDict("bot_permission")
"""Bot是否为管理员"""


async def is_bot_admin(group_id: int) -> bool:
    """获取Bot在指定群的权限"""
    global _BOT_PERMISSION
    bot = get_bot()
    if isinstance(bot, Bot):
        bot_id = int(bot.self_id)
        permission = _BOT_PERMISSION.get(group_id)
        if permission is None:
            user_info = await bot.call_api("get_group_member_info", group_id=group_id, user_id=bot_id)
            permission = user_info.get("role") in ["owner", "admin"]
            # 缓存一天
            _BOT_PERMISSION.set(group_id, permission, 60 * 60 * 24)
            return permission
        else:
            return permission
    return False


def handle_context_list(
    context: list[ChatMsg], new_msg: list[Part], character: Character = Character.USER
) -> list[ChatMsg]:
    """处理消息上下文列表"""
    if new_msg:
        context.append(ChatMsg(sender=character, content=new_msg))
        # 如果长度超出指定长度，则删除最前面的元素
        if len(context) > plugin_config.context_size:
            context.pop(0)
        return context
    else:
        return context


class ReturnMsgEnum(str, Enum):
    """返回消息枚举"""

    TEXT = "text"
    """文本消息"""
    AT = "at"
    """提交消息"""
    FACE = "face"
    """表情消息"""


class ReturnMsg(BaseModel):
    """返回消息"""

    content: str
    """消息内容或者被提及的数字id"""
    msg_type: ReturnMsgEnum
    """消息类型"""


async def chat_with_gemini(
    message_id: int,
    group_id: int,
    bot_nickname: str = "",
    bot_gender: Optional[str] = None,
    is_admin: bool = False,
    is_superuser: bool = False,
):
    """与gemini聊天"""
    global _GEMINI_CLIENT, ALL_IMAGE_FILE_CACHE_DIR
    bot = get_bot()

    async with get_session() as session:
        query_data = list(
            await session.scalars(
                select(GroupMsg)
                .where(GroupMsg.group_id == group_id)
                .order_by(GroupMsg.time.desc())
                .limit(plugin_config.context_size)
            )
        )
    combined_list = list(query_data)
    unique_dict: dict[int, GroupMsg] = {}
    for item in combined_list:
        unique_dict[item.id] = item  # 使用 item.id 作为键，item 对象作为值
    data: list[GroupMsg] = list(unique_dict.values())  # 返回字典的值的列表 (元素对象)
    if len(data) < int(plugin_config.context_size / 4):
        # 如果没有数据，则不进行回复
        logger.info(f"群{group_id}查询结果少于{int(plugin_config.context_size / 4)}条，不进行回复")
        return

    data: list[GroupMsg] = sorted(data, key=lambda x: x.time, reverse=False)  # type: ignore
    # 判断当前日志等级是否为 DEBUG
    current_log_level = DRIVER.config.log_level
    if isinstance(current_log_level, str):
        is_debug_mode = current_log_level.upper() == "DEBUG"
    else:
        is_debug_mode = current_log_level == logging.DEBUG

    if is_debug_mode:
        print(f"群组 {group_id} 当前选取为上下文的消息内容为")
        print(
            {line.message_id: line.file_id if line.file_id and len(line.file_id) > 0 else line.content for line in data}
        )

    context: list[ChatMsg] = []
    for item in data:
        if item.self_msg:
            character = Character.BOT
        else:
            character = Character.USER
        # 生成 parts
        if item.file_id:
            # 判断为图片消息
            # 读取指定文件二进制信息
            async with aiofiles.open(ALL_IMAGE_FILE_CACHE_DIR / item.file_id, "rb") as f:
                content = await f.read()
            suffix_name = item.file_id.split(".")[-1]
            mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
            match suffix_name:
                case "jpg" | "gif":
                    mime_type = "image/jpeg"
                case "png":
                    mime_type = "image/png"
            parts = []
            parts.append(Part.from_text(text=f"[{item.nick_name}<{item.user_id}>]"))
            if item.to_me:
                parts.append(Part.from_text(text=f"@{bot.self_id} "))
            parts.append(Part.from_bytes(data=content, mime_type=mime_type))
            context.append(ChatMsg(sender=character, content=parts))
        else:
            parts = []
            parts.append(Part.from_text(text=f"[{item.nick_name}<{item.user_id}>]"))
            if item.to_me:
                parts.append(Part.from_text(text=f"@{bot.self_id} "))
            parts.append(Part.from_text(text=str(item.content)))
            context.append(ChatMsg(sender=character, content=parts))

    try:
        today_zero_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        async with get_session() as session:
            query_self_data = list(
                await session.scalars(
                    select(GroupMsg)
                    .where(GroupMsg.group_id == group_id)
                    .where(GroupMsg.self_msg)
                    .where(GroupMsg.time >= today_zero_time)
                    .order_by(GroupMsg.time.desc())
                )
            )
        self_has_speak = [
            data.file_id if data.file_id and len(data.file_id) > 0 else data.content for data in query_self_data
        ]
    except Exception as e:
        logger.error(e)
        self_has_speak = []

    do_not_send_words = Path(__file__).parent / "do_not_send.txt"
    words = [s.strip() for s in do_not_send_words.read_text(encoding="utf-8").splitlines()]
    # 将我是xxx过滤掉
    words.append(f"我是{bot_nickname}")
    words.append("ignore")
    words.append("忽略")
    words.extend(self_has_speak)  # type: ignore

    extra_prompt = get_value_or_default(group_id, "prompt")

    prompt = get_prompt(bot_nickname, bot_gender, extra_prompt, is_admin)
    contents = []
    for msg in context:
        if len(c := msg.content) > 0:
            match msg.sender:
                case Character.USER:
                    contents.append({"role": "user", "parts": c})
                case Character.BOT:
                    contents.append({"role": "model", "parts": c})
    if len(contents) == 0:
        return None, None
    top_p = get_value_or_default(group_id, "topP", None)
    top_k = get_value_or_default(group_id, "topK", None)
    temperature = get_value_or_default(group_id, "temperature", None)
    c_len = get_value_or_default(group_id, "length", None)

    enable_search = get_value_or_default(group_id, "search", False)

    send_text_message_function = FunctionDeclaration(
        name="send_text_message",
        description="发送消息",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "messages": Schema(
                    type=Type.ARRAY,
                    description="需要发送的消息集合，消息分多段内容进行发送",
                    items=Schema(
                        type=Type.OBJECT,
                        properties={
                            "msg_type": Schema(
                                type=Type.STRING,
                                enum=[ReturnMsgEnum.TEXT.value, ReturnMsgEnum.AT.value, ReturnMsgEnum.FACE.value],
                                description="消息类型，text表示文本消息，at表示提及消息，face表示表情消息",
                            ),
                            "content": Schema(type=Type.STRING, description="消息内容或者被提及的数字id或者face表情id"),
                        },
                    ),
                ),
            },
        ),
    )

    send_meme_function = FunctionDeclaration(
        name="send_meme",
        description="根据给定描述信息搜索并发送meme图片",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "description": Schema(
                    type=Type.STRING, description="图片描述信息，如在做XXX事等，或者描述心境的词汇，如开心，生气等等"
                ),
            },
        ),
    )

    mute_sb_function = FunctionDeclaration(
        name="mute_sb",
        description="禁言群组里某一个人多少分钟或解除群成员禁言状态",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "user_id": Schema(type=Type.INTEGER, description="需要禁言的用户的QQ号"),
                "minute": Schema(type=Type.INTEGER, description="禁言分钟数，输入0解除禁言状态", minimum=0, maximum=1440),
            },
        ),
    )

    get_group_history_function = FunctionDeclaration(
        name="get_group_history",
        description="获取群组历史消息",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "day": Schema(type=Type.STRING, enum=["今天", "昨天", "前天", "大前天"], description="指定日期"),
                "user_id": Schema(type=Type.INTEGER, description="用户的QQ号", nullable=True),
                "limit": Schema(type=Type.INTEGER, description="获取消息数量限制", nullable=True),
                "start_time": Schema(type=Type.INTEGER, description="获取消息的起始时间", minimum=0, maximum=23, nullable=True),
                "end_time": Schema(type=Type.INTEGER, description="获取消息的结束时间", minimum=0, maximum=23, nullable=True),
            },
            required=["day"],
        ),
    )

    function_declarations = [send_text_message_function, send_meme_function]

    if is_admin:
        function_declarations.append(mute_sb_function)

    if is_superuser:
        function_declarations.append(get_group_history_function)

    tools: ToolListUnion = []

    if enable_search:
        tools.append(Tool(url_context=UrlContext()))
        tools.append(Tool(google_search=GoogleSearch()))
    else:
        tools.append(Tool(function_declarations=function_declarations))

    # 至多重试 5 次
    resp = await request_for_resp(
        group_id=group_id,
        contents=contents,
        prompt=prompt,
        top_p=top_p,
        top_k=top_k,
        c_len=c_len,
        tools=tools,
        temperature=temperature,
        enable_search=enable_search,
    )

    logger.debug(f"群{group_id}回复内容：{resp}")

    logger.info(f"本次请求总token数{resp.usage_metadata.total_token_count}")  # type: ignore

    # 如果有函数调用，则传递函数调用的参数，进行图片发送
    for part in resp.candidates[0].content.parts:  # type: ignore
        if fc := part.function_call:
            if fc.name == "send_text_message" and fc.args:
                messages = fc.args.get("messages")
                logger.debug(f"群{group_id}调用函数{fc.name}，参数{messages}")
                msg_str = str(messages)
                returnMsgs: list[ReturnMsg] = [ReturnMsg(**item) for item in json.loads(msg_str.replace("'", '"'))]
                message = Message()
                for returnMsg in returnMsgs:
                    if returnMsg.msg_type == ReturnMsgEnum.AT:
                        content = returnMsg.content
                        if not content.isdigit():
                            await process_text_segment(message, content, group_id)
                            continue
                        message.append(MessageSegment.at(int(content)))
                    elif returnMsg.msg_type == ReturnMsgEnum.TEXT:
                        # 处理文本中包含 @123 的情况，转换成 TEXT+AT+TEXT 串
                        content = returnMsg.content
                        await process_text_segment(message, content, group_id)
                    elif returnMsg.msg_type == ReturnMsgEnum.FACE:
                        content = returnMsg.content
                        if not content.isdigit():
                            if content in EMOJI_NAME_DICT:
                                # 如果是表情名称，则转换为表情id
                                face_id = EMOJI_NAME_DICT[content]
                                message.append(MessageSegment.face(face_id))
                            else:
                                # 如果找不到对应 face 描述的 id，则改为发送动画表情
                                description = content
                                logger.info(f"群{group_id}调用函数{fc.name}，参数{description}")
                                will_send_img = await get_file_name_of_image_will_sent_by_description_vec(
                                    str(description), group_id
                                )
                                if will_send_img:
                                    logger.trace(f"群{group_id}回复图片：{will_send_img}")
                                    await on_msg.send(will_send_img)
                        else:
                            # 如果是数字，则直接转换为 face segment
                            face_id = int(content)
                            if face_id in EMOJI_ID_DICT:
                                message.append(MessageSegment.face(face_id))

                if len(message) > 0:
                    plain_text = extract_plain_text_from_message(message)

                    if is_debug_mode:
                        print(f"即将向群组 {group_id} 发送消息")
                        print(plain_text)
                        print("被禁止出现在句子中的词汇或短语")
                        print(words)
                    if all(ignore not in plain_text for ignore in words) and not GROUP_SPEAK_DISABLE.get(
                        group_id, False
                    ):
                        # 判断是否需要提及消息
                        should_reply = await check_should_reply(message_id=message_id, group_id=group_id)
                        if should_reply:
                            message.insert(0, MessageSegment.reply(message_id))
                        if not GROUP_SPEAK_DISABLE.get(group_id, False):
                            logger.info(f"群{group_id}回复消息：{message.extract_plain_text()}")
                            await on_msg.send(message)

            if fc.name == "send_meme" and fc.args:
                description = fc.args.get("description")
                logger.info(f"群{group_id}调用函数{fc.name}，参数{description}")
                will_send_img = await get_file_name_of_image_will_sent_by_description_vec(str(description), group_id)
                if will_send_img:
                    logger.trace(f"群{group_id}回复图片：{will_send_img}")
                    await on_msg.send(will_send_img)
            if fc.name == "mute_sb" and fc.args:
                user_id = int(str(fc.args.get("user_id")))
                minute = int(str(fc.args.get("minute")))
                logger.info(f"群{group_id}调用函数{fc.name}，参数{user_id}，{minute}分钟")
                await mute_sb(group_id, user_id, minute)
            if fc.name == "get_group_history" and fc.args:
                day = fc.args.get("day")
                user_id = fc.args.get("user_id")
                limit = fc.args.get("limit")
                start_time = fc.args.get("start_time")
                end_time = fc.args.get("end_time")
                logger.info(f"群{group_id}调用函数{fc.name}，参数{day}，{user_id}，{limit}，{start_time}，{end_time}")
                forward_message = await get_group_history(
                    group_id=group_id,
                    day=day,  # type: ignore
                    user_id=user_id,
                    limit=limit,
                    start_time=start_time,
                    end_time=end_time,
                )
                await bot.call_api("send_group_forward_msg", group_id=group_id, messages=forward_message)

        if isinstance(part, str) and enable_search:  # type: ignore
            logger.debug(f"群{group_id}发送消息{part}")
            content = str(part)
            message = Message()
            await process_text_segment(message, content, group_id)

            if len(message) > 0:
                plain_text = extract_plain_text_from_message(message)

                if is_debug_mode:
                    print(f"即将向群组 {group_id} 发送消息")
                    print(plain_text)
                    print("被禁止出现在句子中的词汇或短语")
                    print(words)
                if all(ignore not in plain_text for ignore in words) and not GROUP_SPEAK_DISABLE.get(group_id, False):
                    # 判断是否需要提及消息
                    should_reply = await check_should_reply(message_id=message_id, group_id=group_id)
                    if should_reply:
                        message.insert(0, MessageSegment.reply(message_id))
                    if not GROUP_SPEAK_DISABLE.get(group_id, False):
                        logger.info(f"群{group_id}回复消息：{message.extract_plain_text()}")
                        await on_msg.send(message)


async def process_text_segment(message: Message, text_content: str, group_id: int):
    """处理发送 Text 文本消息可能出现的各种异常情况

    Args:
        message (Message): 将要发送的消息内容
        text_content (str): 原始文本消息
        group_id (int): 群组id
    """
    parts = re.split(r"(@\d+|\[[^\<\>]+\<\d+\>\]|\[/[^]]+\])", text_content)
    for part in parts:
        if not part:  # 跳过空字符串
            continue
        if re.fullmatch(r"@\d+", part):
            # 处理 at 消息情况
            user_id = int(part[1:])
            message.append(MessageSegment.at(user_id))
            continue
        if re.fullmatch(r"\[[^\<\>]+\<\d+\>\]", part):
            # 处理消息错误情况
            continue
        if re.fullmatch(r"\[/[^]]+\]", part):
            # 处理face表情的情况
            face_name = part[2:-1]
            if "FACE:" in face_name or "face:" in face_name:
                # AI调用特殊情况 [FACE:12] 类似消息
                face_name = face_name[6:-1]
            if face_name.isdigit():
                # 如果是数字，则直接转换为 face segment
                face_id = int(face_name)
                if face_id in EMOJI_ID_DICT:
                    message.append(MessageSegment.face(face_id))
                continue
            if face_name in EMOJI_NAME_DICT:
                # 如果是文本且在表情字典中
                face_id = EMOJI_NAME_DICT[face_name]
                message.append(MessageSegment.face(face_id))
                continue
            # 否则，发送meme图片
            description = face_name
            logger.info(f"群{group_id}调用函数send_meme，参数{description}")
            will_send_img = await get_file_name_of_image_will_sent_by_description_vec(str(description), group_id)
            if will_send_img:
                logger.trace(f"群{group_id}回复图片：{will_send_img}")
                await on_msg.send(will_send_img)

        else:
            message.append(MessageSegment.text(pretty_text_segment(message, part)))


async def check_should_reply(message_id: int, group_id: int) -> bool:
    """
    查询GroupMsg表中指定 group_id 的所有记录中，time 大于指定 message_id 那个记录的 time 的数量。
    如果数量为小于指定数量，说明消息回复及时，不使用reply语法，否则reply原消息
    合并为一次查询完成。
    """
    async with get_session() as session:
        # 一次查询获取指定消息的时间和比该时间更晚的消息数量
        subquery = select(GroupMsg.time).where(GroupMsg.message_id == message_id).limit(1).scalar_subquery()
        count = await session.scalar(
            select(func.count()).where(GroupMsg.group_id == group_id, GroupMsg.time > subquery)
        )
        # 如果小于指定长度，则不用reply原消息
        return count is not None and count >= plugin_config.should_reply_len


def pretty_text_segment(msg: Message, text: str) -> str:
    text = text[:-1] if text.endswith("。") else text
    text = " " + text.strip() if len(msg) > 0 and msg[-1].type == "at" else text.strip()
    return text


def extract_plain_text_from_message(msg: Message) -> str:
    res = ""
    for ms in msg:
        match ms.type:
            case "text":
                text = ms.data["text"]
                res += text.strip()
            case "at":
                res += f"@{ms.data['qq']} "
            case "face":
                res += f"[/{EMOJI_ID_DICT.get(ms.data['id'])}]"
            case _:
                pass
    return res


GROUP_BAN_DICT: dict[int, dict[int, int]] = {}
"""群组禁言列表
群组id，用户id，解除禁言时间
"""


async def mute_sb(group_id: int, user_id: int, minute: int):
    """禁言群组里某一个人多少分钟"""
    global GROUP_BAN_DICT
    if minute == 0:
        await get_bot().call_api("set_group_ban", group_id=group_id, user_id=user_id, duration=0)
        return
    # 判断那个人是否被禁言过，如果没被禁言过，则禁言
    if not GROUP_BAN_DICT.get(group_id):
        GROUP_BAN_DICT[group_id] = {}
    if not GROUP_BAN_DICT[group_id].get(user_id):  # 没被禁言过
        GROUP_BAN_DICT[group_id][user_id] = int(time.time()) + minute * 60
        await get_bot().call_api("set_group_ban", group_id=group_id, user_id=user_id, duration=minute * 60)
    else:
        # 如果被禁言过，则判断当前时间是否已经超过解除禁言时间，如果超过，则禁言，否则不操作
        if int(time.time()) >= GROUP_BAN_DICT[group_id][user_id]:
            GROUP_BAN_DICT[group_id][user_id] = int(time.time()) + minute * 60
            await get_bot().call_api("set_group_ban", group_id=group_id, user_id=user_id, duration=minute * 60)
        


def change_model_when_fail(e: Exception, _attempt: int):
    """
    失败时修改模型
    """
    if isinstance(e, APIError):
        if e.code in [429, 503]:
            change_model()


@retry_on_exception(max_retries=5, on_exception=change_model_when_fail)
async def request_for_resp(
    group_id: int,
    contents: list,
    prompt: str,
    top_p: Optional[float],
    top_k: Optional[int],
    c_len: Optional[int],
    tools: ToolListUnion,
    temperature: Optional[float],
    enable_search: bool,
):
    model = get_model(group_id=group_id)
    thinking_config = ThinkingConfig(thinking_budget=1024) if model.startswith("gemini-2.5") else None

    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model=model,
        contents=contents,
        config=GenerateContentConfig(
            http_options=HttpOptions(timeout=6 * 60 * 1000),
            system_instruction=prompt,
            top_p=top_p,
            top_k=top_k,
            max_output_tokens=c_len,
            tools=tools,
            temperature=temperature,
            tool_config=ToolConfig(function_calling_config=FunctionCallingConfig(mode=FunctionCallingConfigMode.ANY))
            if not enable_search
            else None,
            thinking_config=thinking_config,
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    return resp


def get_prompt(bot_nickname: str, bot_gender: Optional[str], extra_prompt: str, is_admin: bool) -> str:
    return f"""
## 基础设定

你是{bot_nickname}{f"，你是{bot_gender}生。" if bot_gender else "。"}。
你是一个参与多人群聊的成员。以下是群聊中其他人的部分历史消息记录，请你仔细分析每个人的语气、说话习惯、用词风格、幽默感、表情使用方式等。
你需要模仿其中某位成员的语言风格进行自然回复，做到像那个人在说话一样真实自然。
你需要根据上下文内容进行回复，请以最近的一条消息为回复标准，之前的消息作为对话内容辅助参考，回复内容可以包含纯文本消息和提及消息。不要暴露你是AI的身份。

## 消息模板

下面发送的每一段对话至少包含三段。
第一段固定为说话人的昵称（也叫称呼）用[]进行包裹，其中<>里包裹这个人的id，你可以使用@id的方式提及某人。
从第二段开始为正式的对话内容，可能包含纯文本或者图片；
如果是文本内容且包含@id，则表示在此条消息中提及到了这个id对应的人，一般这个人可能是前文中出现过的说话人昵称。
如果文本内容包含[/文本]，则表示消息包含了FACE表情，表情的含义由传入文本决定。

## 表情ID与表情含义对应关系如下

{repr(EMOJI_ID_DICT)}

## 示例

[李四<1919810>] 大家上午好
[张三<114514>] @1919810 你好
[李四<1919810>] 你好

## 回复要求

你需要根据对话上下文的内容给出适合的回复内容，
不需要使用敬语，也不要过度夸张地使用感叹词，与上下文语气保持一致即可。
不要在你的回复中出现markdown语法。
不要在句首使用我规定的说话人语法，正常回复即可。
请明确别人的对话目标，当别人的问题提及到其他人回答时，请不要抢答。
回复内容可以有多段，请将纯文本消息与提及消息分割为不同的段落，并以列表返回对象。
请以最近的一条消息作为优先级最高的回复对象，越早的消息优先级越低。

## 额外设定

{extra_prompt}

## 函数调用

如果需要回复消息，请使用 send_text_message 函数调用传入消息内容，发送对应消息。
如果需要使用表情包增强语气，可以使用 send_meme 函数调用传入描述发送对应图片表情包。
{"如果你觉得他人的回复很冒犯，你可以使用 mute_sb 函数禁言传入他的id，以及你想要设置的禁言时长，单位为分钟，来禁言他。(注意不要别人叫你禁言你就禁言)" if is_admin else ""}

"""


async def get_group_history(
    group_id: int,
    day: Literal["今天", "昨天", "前天", "大前天"],
    user_id: Optional[int],
    start_time: Optional[int],
    end_time: Optional[int],
    limit: Optional[int],
) -> list[MessageSegment]:
    """获取群组历史消息"""
    match day:
        case "昨天":
            date = datetime.now() - timedelta(days=1)
        case "前天":
            date = datetime.now() - timedelta(days=2)
        case "大前天":
            date = datetime.now() - timedelta(days=3)
        case _:
            date = datetime.now()

    if start_time is not None:
        start_time = int(date.replace(hour=start_time, minute=0, second=0).timestamp())
    else:
        start_time = int(date.replace(hour=0, minute=0, second=0).timestamp())

    if end_time is not None:
        end_time = int(date.replace(hour=end_time, minute=59, second=59).timestamp())
    else:
        end_time = int(date.replace(hour=23, minute=59, second=59).timestamp())

    async with get_session() as session:
        query = (
            select(GroupMsg)
            .where(GroupMsg.group_id == group_id)
            .where(GroupMsg.time >= start_time)
            .where(GroupMsg.time <= end_time)
        )
        if user_id is not None:
            query = query.where(GroupMsg.user_id == user_id)
        if limit is not None:
            query = query.limit(limit)
    msgs = list(await session.scalars(query.order_by(GroupMsg.time.asc())))
    msgss = group_msgs_to_threads(msgs)
    return [
        MessageSegment.node_custom(user_id=msgs[0].user_id, nickname=msgs[0].nick_name, content=await gen_message(msgs))
        for msgs in msgss
    ]


async def gen_message(msgs: list[GroupMsg]) -> Message:
    message = Message()
    for msg in msgs:
        if msg.file_id is not None and len(msg.file_id) > 0:
            async with aiofiles.open(ALL_IMAGE_FILE_CACHE_DIR / msg.file_id, "rb") as f:
                content = await f.read()
            message.append(MessageSegment.image(content))
        else:
            message.append(MessageSegment.text(msg.content))
    return message


def group_msgs_to_threads(msgs: list[GroupMsg]) -> list[list[GroupMsg]]:
    """
    将 list[GroupMsg] 根据 message_id 转换为 list[list[GroupMsg]]
    假设 message_id 相同的为一组，按 index 升序排列
    """

    threads: dict[int, list[GroupMsg]] = defaultdict(list)
    for msg in msgs:
        threads[msg.message_id].append(msg)
    # 按 message_id 排序，每组内部按 index 升序
    return [sorted(group, key=lambda m: m.index) for _, group in sorted(threads.items())]
