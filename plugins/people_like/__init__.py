import random
import re
import PIL.Image
import aiofiles
import os
from httpx import AsyncClient
from pathlib import Path
from asyncio import sleep
from typing import Any
from nonebot import get_bot, logger, on_keyword, on_message, require, get_driver

from nonebot.rule import to_me
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, Message
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from google.generativeai.types.content_types import PartType

from common import generate_random_string
from common.struct import ExpirableDict

require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")
require("nonebot_plugin_apscheduler")

import nonebot_plugin_localstore as store
from nonebot_plugin_apscheduler import scheduler
from .setting import get
from .config import Config, plugin_config
from .model import Character, ChatMsg

__plugin_meta__ = PluginMetadata(
    name="people-like",
    description="",
    usage="",
    config=Config,
)

GROUP_MESSAGE_SEQUENT: dict[int, list[ChatMsg]] = {}
"""群号，消息上下文列表
"""

genai.configure(api_key=plugin_config.gemini_key)

GROUP_SPEAK_DISABLE: dict[int, bool] = {}

driver = get_driver()


@driver.on_bot_connect
async def cache_message(bot: Bot):
    global GROUP_MESSAGE_SEQUENT
    # 获取所有群组
    group_list = await bot.get_group_list()
    for group in group_list:
        if (gid := group["group_id"]) in plugin_config.black_list:
            continue
        msgs = GROUP_MESSAGE_SEQUENT.get(gid, [])
        # 获取群消息历史
        history: dict[str, Any] = await bot.call_api(
            "get_group_msg_history", group_id=int(gid), message_seq=0, limit=30, reverseOrder=False
        )
        # 读取历史消息填充到缓存中
        messages = history["messages"]
        for event_dict in messages:
            event_dict["post_type"] = "message"
            event = GroupMessageEvent(**event_dict)
            is_bot_msg = event.user_id == int(bot.self_id)
            target = await extract_msg_in_group_message_event(event)
            if not target:
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


on_msg = on_message()


@on_msg.handle()
async def receive_group_msg(event: GroupMessageEvent) -> None:
    global GROUP_MESSAGE_SEQUENT, GROUP_SPEAK_DISABLE
    do_not_send_words = Path(__file__).parent / "do_not_send.txt"
    words = [s.strip() for s in do_not_send_words.read_text(encoding="utf-8").splitlines()]
    # 群组id
    gid = event.group_id
    # 黑名单内，不检查
    if gid in plugin_config.black_list:
        return
    em = event.message
    # 8位及以上数字字母组合为无意义消息，可能为密码或邀请码之类，过滤不做处理
    if re.match(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$", em.extract_plain_text()):
        return
    msgs = GROUP_MESSAGE_SEQUENT.get(gid, [])
    target = await extract_msg_in_group_message_event(event)
    if not target:
        return
    msgs = handle_context_list(msgs, target)
    GROUP_MESSAGE_SEQUENT.update({gid: msgs})

    # 触发复读
    logger.debug(em)
    if random.random() < plugin_config.repeat_probability and not GROUP_SPEAK_DISABLE.get(gid, False):
        # 过滤掉图片消息，留下meme消息，mface消息，text消息
        new_message: Message = Message()
        for ms in em:
            if ms.type == "image" and ms.__dict__.get("subType") == 0:
                # 图片消息，不处理
                continue
            if ms.type == "voice" or ms.type == "video":
                # 语音、视频消息，不处理
                continue
            if ms.type == "json":
                # json消息，不处理
                continue
            new_message.append(ms)
        await on_msg.finish(new_message)

    # 如果内存中记录到的消息不足指定数量，则不进行处理
    if len(msgs) < plugin_config.context_size:
        return
    # 触发回复
    # 规则：
    # 1. 该群聊没人被闭嘴
    # 2. 满足回复时的概率 plugin_config.reply_probability
    # 3. 如果是提及机器人的消息 则回复概率为原回复概率 plugin_config.reply_probability 的 4 倍
    if (
        (r := random.random()) < plugin_config.reply_probability
        or (event.is_tome() and r < plugin_config.reply_probability * 4)
    ) and not GROUP_SPEAK_DISABLE.get(gid, False):
        resp = await chat_with_gemini(gid, msgs)
        resp = resp.strip()
        logger.info(f"群{gid}回复：{resp}")
        for split_msg in [s_s for s in resp.split("。") if len(s_s := s.strip()) != 0]:
            if all(ignore not in split_msg for ignore in words) and not GROUP_SPEAK_DISABLE.get(gid, False):
                # 先睡，睡完再发
                time = (len(split_msg) / 10 + 1) * plugin_config.msg_send_interval_per_10
                await sleep(time)
                await on_msg.send(split_msg)
                target = [split_msg]
                msgs = handle_context_list(msgs, target, Character.BOT)
        else:
            GROUP_MESSAGE_SEQUENT.update({gid: msgs})


_HTTP_CLIENT = AsyncClient()

_CACHE_DIR = store.get_cache_dir("people_like")


async def extract_msg_in_group_message_event(event: GroupMessageEvent) -> list[PartType]:
    """提取群消息事件中的消息内容"""
    global _HTTP_CLIENT, _CACHE_DIR
    em = event.message
    gid = event.group_id
    target: list[PartType] = []
    for ms in em:
        match ms.type:
            case "text":
                target.append(ms.data["text"])
            case "at":
                target.append(f"@{await get_user_nickname_of_group(gid, int(ms.data['qq']))} ")
            case "image":
                # 下载图片进行处理
                data = await _HTTP_CLIENT.get(ms.data["url"])
                if data.status_code == 200:
                    file_name = _CACHE_DIR / generate_random_string(12)
                    async with aiofiles.open(file_name, "wb") as f:
                        await f.write(data.content)
                    organ = PIL.Image.open(file_name)
                    target.append(organ)
                    # 添加一个定时任务删除缓存图片
                    task_id = generate_random_string(8)
                    scheduler.add_job(remove_cache_image, "interval", days=1, id=task_id, args=[file_name, task_id])
            case _:
                pass
    return target


@driver.on_startup
async def clear_cache_image():
    """启动时清理缓存的图片"""
    global _CACHE_DIR
    for filename in os.listdir(_CACHE_DIR):
        filename = _CACHE_DIR / filename
        if os.path.isfile(filename):
            os.remove(filename)


async def remove_cache_image(filename: Path, task_id: str):
    """删除缓存图片"""
    filename.unlink()
    scheduler.remove_job(task_id)


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


def handle_context_list(
    context: list[ChatMsg], new_msg: list[PartType], character: Character = Character.USER
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


async def chat_with_gemini(group_id: int, context: list[ChatMsg]) -> str:
    """与gemini聊天"""
    nickname = get_bot_nickname_of_group(group_id)
    default_prompt = f"你是{nickname}，请使用纯文本方式根据上文内容回复一句话，不得使用markdown语法"
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
    prompt = get(group_id, "prompt", default_prompt)
    top_p = float(p) if (p := get(group_id, "top_p")) is not None else None
    top_k = int(p) if (p := get(group_id, "top_k")) is not None else None
    c_len = i_p if (p := get(group_id, "length", "100")) is not None and (i_p := int(p)) > 0 else None
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash-exp",
        system_instruction=prompt,
    )
    resp = await model.generate_content_async(
        contents=contents,
        generation_config=GenerationConfig(
            top_p=top_p,
            top_k=top_k,
            max_output_tokens=c_len,
        ),
    )
    return resp.text
