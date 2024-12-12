import random
from asyncio import sleep
from nonebot import logger, on_message
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot
from .setting import get_prompt, get_top_k, get_top_p
import google.generativeai as genai
from google.generativeai.types import GenerationConfig

from .config import Config, plugin_config

__plugin_meta__ = PluginMetadata(
    name="people-like",
    description="",
    usage="",
    config=Config,
)

group_map: dict[int, list[str]] = {}
"""群号，消息上下文列表
"""

genai.configure(api_key=plugin_config.gemini_key)

on_msg = on_message()


@on_msg.handle()
async def receive_group_msg(bot: Bot, event: GroupMessageEvent) -> None:
    global group_map
    gid = event.group_id
    msgs = group_map.get(gid, [])
    target: str = ""
    for ms in event.message:
        if ms.type == "text":
            target += ms.data["text"]
        if ms.type == "at":
            info = await bot.get_group_member_info(group_id=gid, user_id=int(ms.data["qq"]))
            target += f"(人名：{info.get('card', info.get('nickname', ''))})"
        if ms.type == "face":
            pass
        if ms.type == "image":
            # 待办 TODO
            ...
    msgs = handle_context_list(msgs, target)
    group_map.update({gid: msgs})
    # 触发回复
    if random.random() < plugin_config.reply_probability:
        resp = await chat_with_gemini(msgs)
        logger.info(f"群{gid}回复：{resp}")
        resp_msgs = resp.strip().split("。")
        first = True
        for msg in resp_msgs:
            # 间隔时间
            sleep_time = 0 if first else (int(len(msg) / 10) + 1) * plugin_config.msg_send_interval_per_10
            first = False
            msg = msg.strip()
            if len(msg) != 0:
                await sleep(sleep_time)
                await on_msg.send(msg)
                msgs = handle_context_list(msgs, msg)
                group_map.update({gid: msgs})
        return
    # 触发复读
    if random.random() < plugin_config.repeat_probability:
        await on_msg.send(event.message)
        msgs = handle_context_list(msgs, target)
        group_map.update({gid: msgs})
        return


def handle_context_list(context: list[str], new_msg: str) -> list[str]:
    """处理消息上下文列表"""
    context.append(new_msg)
    # 如果长度超出指定长度，则删除最前面的元素
    if len(context) > plugin_config.context_size:
        context.pop(0)
    return context


async def chat_with_gemini(context: list[str]) -> str:
    """与gemini聊天"""
    contents = [{"role": "user", "parts": [content]} for content in context if len(content) != 0]
    if len(contents) == 0:
        return ""
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash-8b",
        system_instruction=get_prompt(),
    )
    resp = await model.generate_content_async(
        contents=contents,
        generation_config=GenerationConfig(
            top_p=get_top_p(), top_k=get_top_k(), max_output_tokens=plugin_config.reply_msg_max_length
        ),
    )
    return resp.text
