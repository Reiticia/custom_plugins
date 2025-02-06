import random
import re
from httpx import AsyncClient
from pathlib import Path
from asyncio import sleep
from typing import Any, Literal, Optional
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
)

from common.struct import ExpirableDict

require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")
require("nonebot_plugin_apscheduler")

import nonebot_plugin_localstore as store
from .setting import get_value_or_default, get_blacklist
from .config import Config, plugin_config
from .model import Character, ChatMsg, GroupMemberDict
from .image_send import _GEMINI_CLIENT, get_file_name_of_image_will_sent

__plugin_meta__ = PluginMetadata(
    name="people-like",
    description="",
    usage="",
    config=Config,
)

GROUP_MESSAGE_SEQUENT: dict[int, list[ChatMsg]] = {}
"""群号，消息上下文列表
"""



GROUP_SPEAK_DISABLE: dict[int, bool] = {}

driver = get_driver()


@driver.on_bot_connect
async def cache_message(bot: Bot):
    global GROUP_MESSAGE_SEQUENT
    # 获取所有群组
    group_list = await bot.get_group_list()
    for group in group_list:
        if str(gid := group["group_id"]) in get_blacklist():
            continue
        msgs = GROUP_MESSAGE_SEQUENT.get(gid, [])
        limit = plugin_config.context_size + 10
        # 获取群消息历史
        history: dict[str, Any] = await bot.call_api(
            "get_group_msg_history", group_id=int(gid), message_seq=0, count=limit, reverseOrder=False
        )
        # 读取历史消息填充到缓存中
        messages = history["messages"]
        for event_dict in messages:
            event_dict["post_type"] = "message"
            event = GroupMessageEvent(**event_dict)
            is_bot_msg = event.user_id == int(bot.self_id)
            target = await extract_msg_in_group_message_event(event)
            if len(target) < 2:
                continue
            # 判断是否是机器人自己发的消息
            if is_bot_msg:
                msgs = handle_context_list(msgs, target, Character.BOT)
            else:
                msgs = handle_context_list(msgs, target)
        GROUP_MESSAGE_SEQUENT.update({gid: msgs})
        logger.info(f"群{gid}消息缓存完成")


shutup = on_keyword(keywords={"闭嘴", "shut up", "shutup", "Shut Up", "Shut up", "滚", "一边去"}, rule=to_me())


@shutup.handle()
async def _(event: GroupMessageEvent):
    global GROUP_SPEAK_DISABLE
    gid = event.group_id
    GROUP_SPEAK_DISABLE.update({gid: True})
    await sleep(300)
    GROUP_SPEAK_DISABLE.update({gid: False})


on_msg = on_message(priority=5)


@on_msg.handle()
async def receive_group_msg(event: GroupMessageEvent) -> None:
    global GROUP_MESSAGE_SEQUENT, GROUP_SPEAK_DISABLE
    # 群组id
    gid = event.group_id
    nickname = await get_bot_nickname_of_group(gid)
    do_not_send_words = Path(__file__).parent / "do_not_send.txt"
    words = [s.strip() for s in do_not_send_words.read_text(encoding="utf-8").splitlines()]
    # 将我是xxx过滤掉
    words.append(f"我是{nickname}")
    # 黑名单内，不检查
    if str(gid) in get_blacklist():
        logger.debug(f"群{gid}消息黑名单内，不处理")
        return
    em = event.message
    # 8位及以上数字字母组合为无意义消息，可能为密码或邀请码之类，过滤不做处理
    if re.match(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$", em.extract_plain_text()):
        return
    msgs = GROUP_MESSAGE_SEQUENT.get(gid, [])
    target = await extract_msg_in_group_message_event(event)
    if len(target) < 2:
        return
    msgs = handle_context_list(msgs, target)
    GROUP_MESSAGE_SEQUENT.update({gid: msgs})

    logger.debug(f"receive: {em}")

    # 触发复读
    if random.random() < plugin_config.repeat_probability and not GROUP_SPEAK_DISABLE.get(gid, False):
        logger.debug(f"群{gid}触发复读")
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

    # 如果内存中记录到的消息不足指定数量，则不进行处理
    if len(msgs) < plugin_config.context_size:
        logger.debug(f"群{gid}消息上下文长度{len(msgs)}不足{plugin_config.context_size}，不处理")
        return
    # 触发回复
    # 规则：
    # 1. 该群聊没有被闭嘴
    # 2. 满足回复时的概率 plugin_config.reply_probability
    # 3. 如果是提及机器人的消息 则回复概率为原回复概率 plugin_config.reply_probability 的 4 倍
    if (
        (
            send := (
                (r := random.random())
                < float(get_value_or_default(gid, "reply_probability", str(plugin_config.reply_probability)))
            )
        )
        or (
            event.is_tome()
            and (
                (r < float(get_value_or_default(gid, "at_reply_probability", str(plugin_config.reply_probability * 4))))
                or send
            )
        )
    ) and not GROUP_SPEAK_DISABLE.get(gid, False):
        resp = await chat_with_gemini(gid, msgs, nickname, (await get_bot_gender()))
        if not resp:
            return
        resp = resp.strip()
        logger.info(f"群{gid}回复：{resp}")
        for split_msg in [s_s for s in resp.split("\n") if len(s_s := s.strip()) != 0]:
            split_msg = remove_first_bracket_at_start(split_msg)  # 修正输出
            if split_msg.endswith("。"):
                split_msg = split_msg[0:-1]
            if all(ignore not in split_msg for ignore in words) and not GROUP_SPEAK_DISABLE.get(gid, False):
                # 先睡，睡完再发
                await sleep_sometime(len(split_msg))
                # 将回复消息种的 @xxx 转换成对应消息段
                split_msg = convert_at_to_at_segment(split_msg, group_id=gid)
                logger.debug(f"群{gid}回复消息：{split_msg}")
                await on_msg.send(split_msg)


GROUP_MEMBER_DICT: dict[int, GroupMemberDict] = {}


def convert_at_to_at_segment(text: str, group_id: int) -> Message:
    """将 @xxx 转换成对应消息段

    Args:
        text (str): 原消息

    Returns:
        str: 转换后的消息
    """
    global GROUP_MEMBER_DICT
    ms = text.split(" ")
    new_ms: list[MessageSegment] = []
    for om in ms:
        m = om.strip()
        # TODO 如果是@开头，则转化成@消息段
        if m.startswith("@"):
            nm = m.removeprefix("@")
            user_id = GROUP_MEMBER_DICT.get(group_id, GroupMemberDict(group_id=group_id, members={})).get_id_by_name(
                user_name=nm
            )
            if user_id is None:
                # 找不到用户，则原样输出
                new_ms.append(MessageSegment.text(om))
            else:
                # 找到用户，则转化成@消息段
                new_ms.append(MessageSegment.at(user_id))
        else:
            new_ms.append(MessageSegment.text(m))

    return Message(new_ms)


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
    global GROUP_MESSAGE_SEQUENT
    gid = event.group_id
    msgs = GROUP_MESSAGE_SEQUENT.get(gid, [])
    target = await extract_msg_in_group_message_event(event)
    if len(target) < 2:
        return
    msgs = handle_context_list(msgs, target, Character.BOT)
    GROUP_MESSAGE_SEQUENT.update({gid: msgs})


def remove_first_bracket_at_start(text: str) -> str:
    """使用正则表达式匹配字符串开头的方括号及其内容，并将其替换为空字符串"""
    return re.sub(r"^\[.*?\]", "", text)


async def sleep_sometime(size: int):
    """根据字数休眠一段时间"""
    time = random.random() * plugin_config.one_word_max_used_time_of_second * size
    await sleep(time)


_HTTP_CLIENT = AsyncClient()

_CACHE_DIR = store.get_cache_dir("people_like")


async def extract_msg_in_group_message_event(event: GroupMessageEvent) -> list[Part]:
    """提取群消息事件中的消息内容"""
    global _HTTP_CLIENT, _CACHE_DIR, GROUP_MEMBER_DICT
    em = event.message
    gid = event.group_id
    target: list[Part] = []
    sender_nickname = await get_user_nickname_of_group(gid, int(event.user_id))

    # 建立对应群组中用户昵称与id的映射关系
    if not (members := GROUP_MEMBER_DICT.get(gid)):
        members = GroupMemberDict(group_id=gid, members={})
    members.add_member(int(event.user_id), sender_nickname)
    GROUP_MEMBER_DICT.update({gid: members})

    target.append(Part.from_text(text=f"[{sender_nickname}]"))
    if event.is_tome():
        target.append(Part.from_text(text=f"@{await get_bot_nickname_of_group(gid)} "))
    for ms in em:
        match ms.type:
            case "text":
                target.append(Part.from_text(text=ms.data["text"]))
            case "at":
                target.append(Part.from_text(text=f"@{await get_user_nickname_of_group(gid, int(ms.data['qq']))} "))
            case "image":
                if plugin_config.image_analyze:
                    # 下载图片进行处理
                    data = await _HTTP_CLIENT.get(ms.data["url"])
                    suffix_name = str(ms.data["file"]).split(".")[-1]
                    mime_type: Literal["image/jpeg", "image/gif", "image/png"] = "image/jpeg"
                    match suffix_name:
                        case "jpg":
                            mime_type = "image/jpeg"
                        case "gif":
                            mime_type = "image/gif"
                        case "png":
                            mime_type = "image/png"
                    if data.status_code == 200:
                        target.append(Part.from_bytes(data=data.content, mime_type=mime_type))
            case _:
                pass
    return target


_USER_OF_GROUP_NICKNAME: dict[int, ExpirableDict[int, str]] = dict()
_BOT_OF_GROUP_NICKNAME: ExpirableDict[int, str] = ExpirableDict("bot_of_group_nickname")


async def get_user_nickname_of_group(group_id: int, user_id: int) -> str:
    """读取程序内存中缓存的用户在指定群组的昵称"""
    global _USER_OF_GROUP_NICKNAME
    gd = _USER_OF_GROUP_NICKNAME.get(group_id, ExpirableDict(str(group_id)))
    name = gd.get(user_id)
    if name is None:
        bot = get_bot()
        info: dict[str, Any] = dict(await bot.call_api("get_group_member_info", group_id=group_id, user_id=user_id))
        nickname: str = str(info.get("card", info.get("nickname", str(info.get("user_id")))))
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
            return str(new_info.get("sex"))
        else:
            return str(info.get("sex"))
    else:
        return None


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


async def chat_with_gemini(
    group_id: int, context: list[ChatMsg], bot_nickname: str = "", bot_gender: Optional[str] = None
) -> Optional[str]:
    """与gemini聊天"""
    global _GEMINI_CLIENT
    default_prompt = f"""你是{bot_nickname}，{f"你是{bot_gender}生，" if bot_gender else ""}如果有人询问你是否为机器人、AI、大模型，要明确否定。
下面发送的每一段对话至少包含两段。第一段固定为说话人的昵称（也叫称呼）用[]进行包裹。
从第二段开始为正式的对话内容，可能包含纯文本或者图片；如果是文本内容且为@开头的文本，则表示在此条消息中提及到了某个人，一般这个人可能是前文中出现过的说话人昵称。
你需要根据对话上下文的内容给出适合的回复内容，不需要使用敬语，也不要过度夸张地使用感叹词，与上下文语气保持一致即可。
不要在你的回复中出现markdown语法。
不要在句首使用我规定的说话人语法，正常回复即可。
如果需要回复表情图片，请使用 send_meme 函数，并传入描述信息
请明确别人的对话目标，当别人的问题提及到其他人回答时，请不要抢答。\n
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
        return ""
    prompt = get_value_or_default(group_id, "prompt", "")
    prompt = default_prompt + prompt
    top_p = float(p) if (p := get_value_or_default(group_id, "top_p")) else None
    top_k = int(p) if (p := get_value_or_default(group_id, "top_k")) else None
    c_len = i_p if (p := get_value_or_default(group_id, "length", "0")) and (i_p := int(p)) > 0 else None

    enable_search = bool(get_value_or_default(group_id, "search"))

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

    tools: ToolListUnion = [Tool(function_declarations=[send_meme_function])]

    if enable_search:
        tools.append(Tool(google_search=GoogleSearch()))

    resp = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=contents,
        config=GenerateContentConfig(
            system_instruction=prompt,
            top_p=top_p,
            top_k=top_k,
            max_output_tokens=c_len,
            tools=tools,
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
    if resp.function_calls:
        for fc in resp.function_calls:
            if fc.name == "send_meme" and fc.args:
                description = fc.args.get("description")
                logger.debug(f"群{group_id}调用函数{fc.name}，参数{description}")
                await get_file_name_of_image_will_sent(str(description), group_id)
    else:
        return res if "send_meme" not in str(res := resp.text) else None
