# 处理 notice 事件
from typing import Any
from nonebot import get_bot, logger, on_notice
from nonebot.adapters import Event
from nonebot_plugin_orm import get_session

from common.struct import ExpirableDict
from .model import GroupMsg

_USER_OF_GROUP_NICKNAME: dict[int, ExpirableDict[int, str]] = dict()


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

def check_group_card_update(event: Event):
    """检查事件为群成员名片修改事件"""
    return event.get_event_name() == "notice.group_card"


@on_notice(rule=check_group_card_update).handle()
async def _(event: Event):
    """更新缓存中的群成员名片"""
    global _USER_OF_GROUP_NICKNAME
    event_model = event.model_dump()
    group_id = event_model["group_id"]
    user_id = event_model["user_id"]
    card_new = event_model["card_new"]
    gd = _USER_OF_GROUP_NICKNAME.get(group_id, ExpirableDict(str(group_id)))
    name = gd.get(user_id)
    if name is not None:
        # 更新缓存
        gd.set(user_id, card_new, gd.ttl(user_id))
    if card_new == '':  # 如果用户清空了群备注
        gd.delete(user_id)
    _USER_OF_GROUP_NICKNAME.update({group_id: gd})


def check_poke(event: Event):
    """检查事件为戳一戳事件"""
    return event.get_event_name() == "notice.notify.poke"


@on_notice(rule=check_poke).handle()
async def _(event: Event):
    """将戳一戳消息插入数据库"""
    global _USER_OF_GROUP_NICKNAME
    event_model = event.model_dump()
    group_id = event_model["group_id"]
    user_id = event_model["user_id"]
    target_id = event_model["target_id"]
    self_id = event_model["self_id"]
    time = event_model["time"]
    if group_id:
        # 获取戳一戳的用户昵称
        nickname = await get_user_nickname_of_group(group_id, user_id)
        target_nickname = await get_user_nickname_of_group(group_id, target_id)
        raw_info = event_model["raw_info"]
        action_name = raw_info[2]["txt"]
        detail_name = raw_info[4]["txt"]
        content = f"{nickname}({user_id}){action_name}{target_nickname}({target_id}){detail_name}"
        # 将消息插入数据库
        async with get_session() as session:
            session.add(GroupMsg(
                message_id=None,
                group_id=group_id,
                user_id=user_id,
                self_msg=user_id == self_id,
                to_me=target_id == self_id,
                index=0,
                nick_name=nickname,
                content=content,
                file_id=None,
                time=time
            ))
            await session.commit()

def check_group_mute(event: Event):
    return event.get_event_name() == "notice.group_ban.ban" or event.get_event_name() == "notice.group_ban.lift_ban"


@on_notice(rule=check_group_mute).handle()
async def _(event: Event):
    """将禁言与被禁言通知事件加入数据库"""
    event_model = event.model_dump()
    group_id = event_model["group_id"]
    operator_id = event_model["operator_id"]
    user_id = event_model["user_id"]
    self_id = event_model["self_id"]
    sub_type = event_model["sub_type"]
    duration = event_model["duration"]
    time = event_model["time"]
    if group_id:
        operator_nickname = await get_user_nickname_of_group(group_id, operator_id)
        nickname = await get_user_nickname_of_group(group_id, user_id)
        content = f"{nickname}({user_id})被{operator_nickname}({operator_id}){f'禁言{duration/60}分钟' if sub_type == 'ban' else '解除禁言'}"
        async with get_session() as session:
            session.add(GroupMsg(
                message_id=None,
                group_id=group_id,
                user_id=user_id,
                self_msg=operator_id == self_id,
                to_me=user_id == self_id,
                index=0,
                nick_name=nickname,
                content=content,
                file_id=None,
                time=time
            ))
            await session.commit()