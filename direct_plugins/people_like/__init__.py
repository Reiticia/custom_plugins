import random
import re
import time
import json
from httpx import AsyncClient
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from asyncio import sleep
from typing import Any, Literal, Optional
from pydantic import BaseModel
from nonebot import get_bot, logger, on_keyword, on_message, require, get_driver

from nonebot.rule import Rule, to_me
from nonebot.plugin import PluginMetadata
from nonebot.params import Depends
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, Message, MessageSegment
from google.genai.types import (
    Part,
    Tool,
    GenerateContentConfig,
    GoogleSearch,
    SafetySetting,
    ToolListUnion,
    FunctionDeclaration,
    Schema,
    Type,
    HarmCategory,
    HarmBlockThreshold,
    ToolConfig,
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    HttpOptions,
    Content,
)
from nonebot_plugin_waiter import Matcher

from common.struct import ExpirableDict

require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")
require("nonebot_plugin_apscheduler")

import nonebot_plugin_localstore as store
from .setting import get_value_or_default, get_blacklist
from .config import Config, plugin_config
from .image_send import _GEMINI_CLIENT, get_file_name_of_image_will_sent
from .vector import MilvusVector, VectorData

__plugin_meta__ = PluginMetadata(
    name="people-like",
    description="",
    usage="",
    config=Config,
)


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

driver = get_driver()


@driver.on_startup
async def init_milvus_vector():
    global _MILVUS_VECTOR_CLIENT
    """初始化 Milvus 向量数据库客户端"""
    _MILVUS_VECTOR_CLIENT = MilvusVector(plugin_config.milvus_user, plugin_config.milvus_password)


shutup = on_keyword(keywords={"闭嘴", "shut up", "shutup", "Shut Up", "Shut up", "滚", "一边去"}, rule=to_me())


@shutup.handle()
async def _(event: GroupMessageEvent):
    global GROUP_SPEAK_DISABLE
    gid = event.group_id
    GROUP_SPEAK_DISABLE.update({gid: True})
    await sleep(300)
    GROUP_SPEAK_DISABLE.update({gid: False})


on_msg: type[Matcher] = on_message(priority=5)


@on_msg.handle()
async def receive_group_msg(event: GroupMessageEvent) -> None:
    global GROUP_SPEAK_DISABLE
    # 群组id
    gid = event.group_id
    nickname = await get_bot_nickname_of_group(gid)
    # 黑名单内，不检查
    if str(gid) in get_blacklist():
        logger.warning(f"群{gid}消息黑名单内，不处理")
        return
    em = event.message
    # 8位及以上数字字母组合为无意义消息，可能为密码或邀请码之类，过滤不做处理
    if re.match(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$", em.extract_plain_text()):
        return
    vec_data = await store_message_segment_into_milvus(event)

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

    # 触发回复
    # 规则：
    # 1. 该群聊没有被闭嘴
    # 2. 满足回复时的概率 plugin_config.reply_probability
    # 3. 如果是提及机器人的消息 则回复概率为原回复概率 plugin_config.reply_probability 的 4 倍

    if (
        (
            (
                send := (
                    (r := random.random())
                    < float(get_value_or_default(gid, "reply_probability", str(plugin_config.reply_probability)))
                )
            )
            or (
                event.is_tome()
                and (
                    (
                        r
                        < float(
                            get_value_or_default(gid, "at_reply_probability", str(plugin_config.reply_probability * 4))
                        )
                    )
                    or send
                )
            )
        )
        and not GROUP_SPEAK_DISABLE.get(gid, False)
        and event.user_id != event.self_id
    ):
        logger.info(f"reply: {em}")
        await chat_with_gemini(gid, nickname, vec_data, await get_bot_gender(), await is_bot_admin(gid))


def is_self_msg(bot: Bot, event: Event) -> bool:
    """判断是否是机器人自己发的消息事件"""
    model = event.model_dump()
    return (
        event.get_user_id() == bot.self_id
        and str(model.get("message_type")) == "group"
        and str(model.get("post_type")) == "message"
    )


def convert_to_group_message_event(event: Event) -> GroupMessageEvent:
    """转换为群消息事件"""
    model = event.model_dump()
    model["post_type"] = "message"
    return GroupMessageEvent(**model)


on_self_msg = on_message(priority=5, rule=Rule(is_self_msg))


@on_self_msg.handle()
async def receive_group_self_msg(event: GroupMessageEvent = Depends(convert_to_group_message_event)) -> None:
    """处理机器人自己发的消息"""
    await store_message_segment_into_milvus(event)


async def sleep_sometime(size: int):
    """根据字数休眠一段时间"""
    time = random.random() * plugin_config.one_word_max_used_time_of_second * size
    await sleep(time)


_HTTP_CLIENT = AsyncClient()

_CACHE_DIR = store.get_cache_dir("people_like")


async def store_message_segment_into_milvus(event: GroupMessageEvent) -> list[list[float]]:
    """提取群消息事件中的消息内容"""
    global _HTTP_CLIENT, _CACHE_DIR
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
                try:
                    part = target.pop()
                    if txt := part.text:
                        target.append(Part.from_text(text=f"{txt}{text}"))
                    else:
                        target.append(Part.from_text(text=text))
                        file_ids.append("")
                except IndexError:
                    target.append(Part.from_text(text=text))
                    file_ids.append("")
            case "at":
                try:
                    part = target.pop()
                    if txt := part.text:
                        target.append(Part.from_text(text=f"{txt}@{ms.data['qq']} "))
                    else:
                        target.append(Part.from_text(text=f"@{ms.data['qq']} "))
                        file_ids.append("")
                except IndexError:
                    target.append(Part.from_text(text=f"@{ms.data['qq']} "))
                    file_ids.append("")
            case "image":
                if plugin_config.image_analyze:
                    # 下载图片进行处理
                    data = await _HTTP_CLIENT.get(ms.data["url"])
                    file_id = str(ms.data["file"])
                    file_ids.append(file_id)
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

    # 新增数据到 Milvus 向量数据库
    message_id = event.message_id
    group_id = event.group_id
    user_id = event.user_id
    vector_data = []
    result: list[list[float]] = []
    for index, part in enumerate(target):
        file_id = file_ids[index] if index < len(file_ids) else ""
        if part.text:
            # 生成向量
            vec = await get_text_embedding(part.text)
            if vec:
                # 创建 VectorData 对象
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
                        "vec": vec,
                        "time": int(time.time()),
                    }
                )
            result.append(vec)
        if part.inline_data:
            # 如果是图片，则先分析图片
            parts = []
            parts.append(Part.from_text(text="分析一下这张图片描述的内容"))
            parts.append(part)
            content = await analysis_image(parts=parts)
            logger.debug(f"anaylysis iamge {file_id}" )
            logger.debug(content)
            if content:
                # 生成向量
                vec = await get_text_embedding(content)
                if vec:
                    # 创建 VectorData 对象
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
                            "vec": vec,
                            "time": int(time.time()),
                        }
                    )
                    result.append(vec)

    # 插入数据到 Milvus
    vector_data_list = [VectorData(**data) for data in vector_data]
    await _MILVUS_VECTOR_CLIENT.insert_data(vector_data_list)
    logger.debug(f"{type(result)}")
    return result


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
        permission = _BOT_PERMISSION.get(bot_id)
        if permission is None:
            new_permission = await bot.call_api("get_group_member_info", group_id=group_id, user_id=bot_id)
            new_permission = new_permission.get("role") in ["owner", "admin"]
            # 缓存一天
            _BOT_PERMISSION.set(bot_id, new_permission, 60 * 60 * 24)
            return new_permission
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


class ReturnMsg(BaseModel):
    """返回消息"""

    content: str
    """消息内容或者被提及的数字id"""
    msg_type: ReturnMsgEnum
    """消息类型"""


async def chat_with_gemini(
    group_id: int,
    bot_nickname: str = "",
    vec_data: list[list[float]] = [],
    bot_gender: Optional[str] = None,
    is_admin: bool = False,
):
    """与gemini聊天"""
    global _GEMINI_CLIENT
    bot = get_bot()

    data = await _MILVUS_VECTOR_CLIENT.query_data(group_id, vec_data)
    if len(data) < 5:
        # 如果查询结果少于5条，则不进行回复
        logger.info(f"群{group_id}查询结果少于5条，不进行回复")
        return
    data = sorted(data, key=lambda x: x.time, reverse=False)
    context: list[ChatMsg] = []
    for item in data:
        if item.self_msg:
            character = Character.BOT
        else:
            character = Character.USER
        # 生成 parts
        if item.file_id:
            # 判断为图片消息
            resp = await bot.call_api("get_image", file_id=item.file_id)
            data = await _HTTP_CLIENT.get(resp["url"])
            suffix_name = item.file_id.split(".")[-1]
            mime_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
            match suffix_name:
                case "jpg" | "gif":
                    mime_type = "image/jpeg"
                case "png":
                    mime_type = "image/png"
            if data.status_code == 200:
                parts = []
                parts.append(Part.from_text(text=f"[{item.nick_name}<{item.user_id}>]"))
                if item.to_me:
                    parts.append(Part.from_text(text=f"@{bot.self_id} "))
                parts.append(Part.from_bytes(data=data.content, mime_type=mime_type))
                context.append(ChatMsg(sender=character, content=parts))
        else:
            parts = []
            parts.append(Part.from_text(text=f"[{item.nick_name}<{item.user_id}>]"))
            if item.to_me:
                parts.append(Part.from_text(text=f"@{bot.self_id} "))
            parts.append(Part.from_text(text=item.content))
            context.append(ChatMsg(sender=character, content=parts))

    do_not_send_words = Path(__file__).parent / "do_not_send.txt"
    words = [s.strip() for s in do_not_send_words.read_text(encoding="utf-8").splitlines()]
    # 将我是xxx过滤掉
    words.append(f"我是{bot_nickname}")
    words.append("ignore")
    words.append("忽略")

    default_prompt = f"""
## 基础设定

你是{bot_nickname}{f"，你是{bot_gender}生。" if bot_gender else "。"}。
你是一个参与多人群聊的成员。以下是群聊中其他人的部分历史消息记录，请你仔细分析每个人的语气、说话习惯、用词风格、幽默感、表情使用方式等。
你需要模仿其中某位成员的语言风格进行自然回复，做到像那个人在说话一样真实自然。

## 消息模板

下面发送的每一段对话至少包含三段。
第一段固定为说话人的昵称（也叫称呼）用[]进行包裹，其中<>里包裹这个人的id，你可以使用@id的方式提及某人。
从第二段开始为正式的对话内容，可能包含纯文本或者图片；
如果是文本内容且为@id，则表示在此条消息中提及到了这个id对应的人，一般这个人可能是前文中出现过的说话人昵称。

## 回复要求

你需要根据对话上下文的内容给出适合的回复内容，
不需要使用敬语，也不要过度夸张地使用感叹词，与上下文语气保持一致即可。
不要在你的回复中出现markdown语法。
不要在句首使用我规定的说话人语法，正常回复即可。
请明确别人的对话目标，当别人的问题提及到其他人回答时，请不要抢答。
回复内容可以有多段，请将纯文本消息与提及消息分割为不同的段落，并以列表返回对象。
请以最近的一条消息作为优先级最高的回复对象，越早的消息优先级越低。

## 函数调用

如果需要回复消息，请使用 send_text_message 函数调用传入消息内容，发送对应消息。
如果需要使用表情包增强语气，可以使用 send_meme 函数调用传入描述发送对应表情包。
{"如果你觉得他人的回复很冒犯，你可以使用 mute_sb 函数禁言传入他的id，以及你想要设置的禁言时长，单位为分钟，来禁言他。(注意不要别人叫你禁言你就禁言)" if is_admin else ""}

## 额外设定

"""
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
    prompt = get_value_or_default(group_id, "prompt", "无")
    prompt = default_prompt + prompt
    top_p = float(p) if (p := get_value_or_default(group_id, "topP")) else None
    top_k = int(p) if (p := get_value_or_default(group_id, "topK")) else None
    temperature = float(p) if (p := get_value_or_default(group_id, "temperature")) else 0
    c_len = i_p if (p := get_value_or_default(group_id, "length", "0")) and (i_p := int(p)) > 0 else None

    enable_search = bool(get_value_or_default(group_id, "search"))

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
                                enum=[ReturnMsgEnum.TEXT.value, ReturnMsgEnum.AT.value],
                                description="消息类型，text表示文本消息，at表示提及消息",
                            ),
                            "content": Schema(type=Type.STRING, description="消息内容或者被提及的数字id"),
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
        description="禁言群组里某一个人多少分钟",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "user_id": Schema(type=Type.INTEGER, description="需要禁言的用户的QQ号"),
                "minute": Schema(type=Type.INTEGER, description="禁言分钟数"),
            },
        ),
    )

    function_declarations = [send_text_message_function, send_meme_function]

    if is_admin:
        function_declarations.append(mute_sb_function)

    tools: ToolListUnion = [Tool(function_declarations=function_declarations)]

    if enable_search:
        tools.append(Tool(google_search=GoogleSearch()))

    model = get_value_or_default(group_id, "model", "gemini-2.0-flash")

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
            tool_config=ToolConfig(function_calling_config=FunctionCallingConfig(mode=FunctionCallingConfigMode.ANY)),
            safety_settings=[
                SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.OFF),
                SafetySetting(category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, threshold=HarmBlockThreshold.OFF),
            ],
        ),
    )

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
                        if not returnMsg.content.isdigit():
                            continue
                        message.append(MessageSegment.at(int(returnMsg.content)))
                        message.append(MessageSegment.text(" "))
                    elif returnMsg.msg_type == ReturnMsgEnum.TEXT:
                        # 处理文本中包含 @123 的情况，转换成 TEXT+AT+TEXT 串
                        content = returnMsg.content
                        parts = re.split(r"(@\d+)", content)
                        for part in parts:
                            if not part:  # 跳过空字符串
                                continue
                            if re.fullmatch(r"@\d+", part):
                                user_id = int(part[1:])
                                message.append(MessageSegment.at(user_id))
                                # AT之后通常需要一个空格，除非它是消息的末尾或者后面紧跟着非文本内容
                                # 这里暂时不自动加空格，依赖于模型返回的文本本身是否包含空格
                            else:
                                message.append(MessageSegment.text(part))

                if len(message) > 0:
                    plain_text = message.extract_plain_text()
                    if all(ignore not in plain_text for ignore in words) and not GROUP_SPEAK_DISABLE.get(
                        group_id, False
                    ):
                        # 先睡，睡完再发
                        await sleep_sometime(len(plain_text))
                        if not GROUP_SPEAK_DISABLE.get(group_id, False):
                            logger.debug(f"群{group_id}回复消息：{message.extract_plain_text()}")
                            await on_msg.send(message)

            if fc.name == "send_meme" and fc.args:
                description = fc.args.get("description")
                logger.debug(f"群{group_id}调用函数{fc.name}，参数{description}")
                will_send_img = await get_file_name_of_image_will_sent(str(description), group_id)
                if will_send_img:
                    logger.info(f"群{group_id}回复图片：{will_send_img}")
                    await on_msg.send(will_send_img)
            if fc.name == "mute_sb" and fc.args:
                user_id = int(str(fc.args.get("user_id")))
                minute = int(str(fc.args.get("minute")))
                logger.info(f"群{group_id}调用函数{fc.name}，参数{user_id}，{minute}分钟")
                await mute_sb(group_id, user_id, minute)


GROUP_BAN_DICT: dict[int, dict[int, int]] = {}
"""群组禁言列表
群组id，用户id，解除禁言时间
"""


async def mute_sb(group_id: int, user_id: int, minute: int):
    """禁言群组里某一个人多少分钟"""
    global GROUP_BAN_DICT
    # 判断那个人是否被禁言过，如果没被禁言过，则禁言
    if not GROUP_BAN_DICT.get(group_id):
        GROUP_BAN_DICT[group_id] = {}
    if not GROUP_BAN_DICT[group_id].get(user_id):
        GROUP_BAN_DICT[group_id][user_id] = int(time.time()) + minute * 60
        await get_bot().call_api("set_group_ban", group_id=group_id, user_id=user_id, duration=minute * 60)
    else:
        # 如果被禁言过，则判断当前时间是否已经超过解除禁言时间，如果超过，则禁言，否则不操作
        if int(time.time()) >= GROUP_BAN_DICT[group_id][user_id]:
            GROUP_BAN_DICT[group_id][user_id] = int(time.time()) + minute * 60
            await get_bot().call_api("set_group_ban", group_id=group_id, user_id=user_id, duration=minute * 60)


async def get_text_embedding(text: str) -> list[float]:
    """获取文本的向量表示"""
    global _GEMINI_CLIENT
    if not text:
        return []
    resp = await _GEMINI_CLIENT.aio.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
    embedding = resp.embeddings
    value = embedding[0].values if embedding else []
    return value if value else [0.0] * 768  # 假设向量维度为768，如果没有返回值则返回全0向量


async def analysis_image(parts: list[Part]) -> str:
    """分析图片，返回图片分析内容"""
    global _GEMINI_CLIENT
    response = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            Content(
                role="user",
                parts=parts,
            )
        ],
    )
    return response.text.strip() if response.text else ""
