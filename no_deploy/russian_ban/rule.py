import re
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Bot

from nonebot.params import CommandStart
from nonebot import logger


def check_mute_sb(
    bot: Bot, event: GroupMessageEvent, cs: str = CommandStart(), cmd: tuple[str, ...] = ("mute sb", "msb")
) -> bool:
    """判断事件是否为 mute sb 命令

    Args:
        event (GroupMessageEvent): 群组消息事件
        cs (str, optional): 指令前缀. Defaults to CommandStart().
        cmd (tuple[str, ...]): 指令. Defaults to ("mute sb", "msb").

    Returns:
        bool: 匹配是否成功
    """
    logger.debug(f"cs: {cs}")
    if not (msg := event.message.extract_plain_text().strip()).startswith(cs):
        return False
    logger.debug(f"cmd: {cmd}")
    if msg.removeprefix(cs).strip() not in cmd:
        return False
    return True


def check_mute_sb_p_at_st(
    bot: Bot, event: GroupMessageEvent, cs: str = CommandStart(), cmd: tuple[str, ...] = ("mute schedule", "ms")
) -> bool:
    """在某时某分让某人被禁言某段时间

    Args:
        event (GroupMessageEvent): 消息事件
        cs (str): 指令前缀. Defaults to CommandStart().
        cmd (tuple[str, ...]): 指令. Defaults to ("mute sb", "msb").

    Returns:
        bool: 是否匹配
    """
    message = event.get_message()
    if len(message) != 3:
        return False

    text_0: str = message[0].data.get("text", "").strip()
    # 判断指令前缀
    if not text_0.startswith(cs):
        return False

    # 判断指令
    for c in cmd:
        if text_0.removeprefix(cs).strip().startswith(c):
            break
    else:
        return False

    if message[1].type != "at" or message[2].type != "text":
        return False

    text_2 = message[2].data.get("text", "").strip()
    pattern = r"^(\d+)\s*at\s*([01]?\d|2[0-3])(:[0-5]?\d)?$"
    if re.match(pattern, text_2):
        return True
    return False
