from pathlib import Path
import random
import re
from asyncio import sleep
from nonebot import logger, on_keyword, on_message, require

from nonebot.rule import to_me
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot, Message
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from pyparsing import C

require("nonebot_plugin_localstore")

from .setting import get_prompt, get_top_k, get_top_p, get_len
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

on_msg = on_message()

shutup = on_keyword(keywords={"闭嘴", "shut up", "shutup", "Shut Up", "Shut up"}, rule=to_me())
GROUP_SPEAK_DISABLE: dict[int, bool] = {}


@shutup.handle()
async def _(event: GroupMessageEvent):
    global GROUP_SPEAK_DISABLE
    gid = event.group_id
    GROUP_SPEAK_DISABLE.update({gid: True})
    await sleep(300)
    GROUP_SPEAK_DISABLE.update({gid: False})


@on_msg.handle()
async def receive_group_msg(bot: Bot, event: GroupMessageEvent) -> None:
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
    target: str = ""
    for ms in em:
        match ms.type:
            case "text":
                target += ms.data["text"]
            case "at":
                info = await bot.get_group_member_info(group_id=gid, user_id=int(ms.data["qq"]))
                target += f"@{info.get('card', info.get('nickname', str(info.get('user_id'))))} "
            case _:
                pass
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
    if random.random() < plugin_config.reply_probability and not GROUP_SPEAK_DISABLE.get(gid, False):
        resp = await chat_with_gemini(msgs)
        resp = resp.strip()
        logger.info(f"群{gid}回复：{resp}")
        for split_msg in [s_s for s in resp.split("。") if len(s_s := s.strip()) != 0]:
            if all(ignore not in split_msg for ignore in words) and not GROUP_SPEAK_DISABLE.get(gid, False):
                await on_msg.send(split_msg)
                target = split_msg
                msgs = handle_context_list(msgs, target, Character.BOT)
                time = (len(split_msg) / 10 + 1) * plugin_config.msg_send_interval_per_10
                await sleep(time)
        else:
            GROUP_MESSAGE_SEQUENT.update({gid: msgs})



def handle_context_list(context: list[ChatMsg], new_msg: str, character: Character = Character.USER) -> list[ChatMsg]:
    """处理消息上下文列表"""
    if new_msg:
        context.append(ChatMsg(sender=character, content=new_msg))
        # 如果长度超出指定长度，则删除最前面的元素
        if len(context) > plugin_config.context_size:
            context.pop(0)
        return context
    else:
        return context


async def chat_with_gemini(context: list[ChatMsg]) -> str:
    """与gemini聊天"""
    contents = []
    for msg in context:
        if len(c := msg.content) > 0:
            match msg.sender:
                case Character.USER:
                    contents.append({"role": "user", "parts": [c]})
                case Character.BOT:
                    contents.append({"role": "model", "parts": [c]})
    if len(contents) == 0:
        return ""
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash-exp",
        system_instruction=get_prompt(),
    )
    resp = await model.generate_content_async(
        contents=contents,
        generation_config=GenerationConfig(
            top_p=get_top_p(),
            top_k=get_top_k(),
            max_output_tokens=c_len if ((c_len := get_len()) and c_len > 0) else None,
        ),
    )
    return resp.text
