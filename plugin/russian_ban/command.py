import re
from .schedule import save, muted_list_dict, mute_history
from datetime import datetime
from nonebot import on_command
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg
from nonebot.message import run_preprocessor
from nonebot.adapters.onebot.v11 import (
    Bot,
    GROUP_OWNER,
    GroupMessageEvent,
    PrivateMessageEvent,
    MessageEvent,
    Message,
    MessageSegment,
)
from nonebot_plugin_waiter import waiter
from random import choices
from loguru import logger
from .config import config
from asyncio import Lock



switch = True
"""ban switch
"""

random_mute_dict = {
    0: 128,
    1: 64,
    2: 32,
    5: 16,
    10: 8,
    30: 4,
    60: 2,
}
"""random ban dict
"""


random_mute_switch = True


@run_preprocessor
async def random_mute(bot: Bot, event: GroupMessageEvent):
    """random ban someone

    Args:
        bot (Bot): bot object
        event (Event): group message event
    """
    global switch, random_mute_dict, muted_list_dict
    # 如果处于关闭状态，则不检测
    if not switch:
        return
    if event.sender.role in ["admin", "owner"]:
        return
    # check someone has been banned
    keys = list(random_mute_dict.keys())
    weights = list(random_mute_dict.values())
    try:
        v = muted_list_dict[f"{event.group_id}:{event.user_id}"]
        # If someone has been banned, decreate the weight of a 0-minute banand and
        # increate the weight of a 60-minute ban based on the number of previous bans
        if config.increase_probability:
            weights[0] >>= v["count"]
            weights[-1] <<= v["count"]
        # If someone has been banned, increase the duration of the ban time
        if config.increase_duration:
            keys = [i << v["count"] for i in keys]
    except KeyError:
        # someone has not been banned
        v = {"time": 0, "count": 0}
    [min_res] = choices(keys, weights=weights, k=1)
    min_res = min_res * 60
    if min_res != 0:
        # ban fail, end process
        await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=min_res)
        mute_history.append(
            {"group_id": event.group_id, "user_id": event.user_id, "start_time": event.time, "duration": min_res / 60}
        )
        logger.info(f"{event.user_id}在{event.group_id}于{event.time}时被禁言{min_res}秒")
        v["time"] = event.time + min_res
        v["count"] += 1
        muted_list_dict[f"{event.group_id}:{event.user_id}"] = v
        save()


permit_roles = GROUP_OWNER | SUPERUSER

un_mute_all = on_command(cmd="mute clear", permission=permit_roles)


@un_mute_all.handle()
async def _(bot: Bot, event: MessageEvent):
    global muted_list_dict
    for key, value in muted_list_dict.items():
        [group_id, user_id] = key.split(":")
        # if member still banned
        if value["time"] > event.time:
            # if it is group message, check the group_id and unban member of the group
            if isinstance(event, GroupMessageEvent) and str(event.group_id) == group_id:
                await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=0)
            # if it is private message, unban all
            if isinstance(event, PrivateMessageEvent):
                await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=0)
    # clear muted list of this group
    if isinstance(event, GroupMessageEvent):
        muted_list_dict = {k: v for k, v in muted_list_dict.items() if k.split(":")[0] != str(event.group_id)}
    else:
        muted_list_dict.clear()
    save()
    await un_mute_all.finish("已解除所有禁言")


query = on_command(cmd="mute query", permission=permit_roles)


@query.handle()
async def _(event: MessageEvent):
    global muted_list_dict
    members = dict_group_by_group_id(muted_list_dict)
    if isinstance(event, GroupMessageEvent):
        try:
            members_group = members[str(event.group_id)]
            if not members_group:
                await query.finish("当前没有禁言名单")
            else:
                msg = "当前禁言名单："
                for key, value in members_group.items():
                    msg += f"\n{key} 禁言次数：{value['count']}"
                await query.finish(msg)
        except KeyError:
            await query.finish("当前没有禁言名单")
    else:
        if not members:
            await query.finish("当前没有禁言名单")
        else:
            msg = "当前禁言名单："
            for group_id, value in members.items():
                msg += f"\n群组: {group_id}"
                for user_id, info in value.items():
                    msg += f"\n{user_id} 禁言次数: {info['count']}"
            await query.finish(msg)


mute_history_cmd = on_command(cmd="mute history", permission=permit_roles)


@mute_history_cmd.handle()
async def _(event: MessageEvent):
    global mute_history
    if isinstance(event, GroupMessageEvent):
        mute_history = [e for e in mute_history if e["group_id"] == event.group_id]
        if not mute_history:
            await mute_history_cmd.finish("无禁言记录")
        res = "本群禁言历史: "
        for item in mute_history:
            dt = datetime.fromtimestamp(float(item["start_time"]))
            res += f"\n{item['user_id']}于{dt.hour:02}:{dt.minute:02}被禁言{int(item['duration'])}分钟"
        await mute_history_cmd.finish(res)
    else:
        mute_history_dict_by_group = lst_group_by_group_id(mute_history)
        if not mute_history_dict_by_group:
            await mute_history_cmd.finish("无禁言记录")
        res = "禁言历史: "
        for g, lst in mute_history_dict_by_group.items():
            res += f"\n群{g}"
            for item in lst:
                dt = datetime.fromtimestamp(float(item["start_time"]))
                res += f"\n{item['user_id']}于{dt.hour:02}:{dt.minute:02}被禁言{int(item['duration'])}分钟"
        await mute_history_cmd.finish(res)


def lst_group_by_group_id(history: list[dict[str, int]]) -> dict[int, list[dict[str, int]]]:
    """mute history grouping

    Args:
        history (list[dict[str, int]]): mute history
    Returns:
        dict[int, list[dict[str, int]]]: result by group_id
    """
    res: dict[int, list[dict[str, int]]] = {}
    for line in history:
        group_id = line["group_id"]
        user_id_list = res.get(group_id)
        if not user_id_list:
            user_id_list = [line]
            res[group_id] = user_id_list
        else:
            user_id_list.append(line)
    return res


def dict_group_by_group_id(members: dict[str, dict[str, int]]) -> dict[str, dict[str : dict[str, int]]]:
    """ban list grouping

    Args:
        members (dict[str : dict[str, int]]): ban list
    Returns:
        dict[str, dict[str : dict[str, int]]]: result by group_id
    """
    res: dict[str, dict[str, dict[str, int]]] = {}
    for k, v in members.items():
        [group_id, user_id] = k.split(":")
        user_id_dict = res.get(group_id)
        if not user_id_dict:
            user_id_dict = {}
            user_id_dict[user_id] = v
            res[group_id] = user_id_dict
        else:
            user_id_dict[user_id] = v
    return res

mute_sb_cmd = on_command(cmd="mute sb")

@mute_sb_cmd.handle()
async def mute_sb(bot: Bot, event: GroupMessageEvent):
    await mute_sb_cmd.send("请输入QQ号")

    @waiter(waits=["message"], keep_session=True)
    async def check_qq(event: GroupMessageEvent):
        ms = event.get_message()[0]
        return str(ms.data["qq"]) if ms.type == "at" else str(ms.data["text"])

    async for qq in check_qq(timeout=20, retry=5, prompt="输入错误，请@某人或输入qq号。剩余次数: {count}"):
        if qq is None:
            await mute_sb_cmd.finish("等待超时")
        if not qq.isdigit():
            continue
        break
    else:
        await mute_sb_cmd.finish("输入失败")
    await mute_sb_cmd.send("请输入禁言时间，单位分钟")

    @waiter(waits=["message"], keep_session=True)
    async def check_time(event: GroupMessageEvent):
        return event.get_plaintext()

    async for mute_time in check_time(timeout=20, retry=5, prompt="输入错误，请输入数字。剩余次数: {count}"):
        if mute_time is None:
            await mute_sb_cmd.finish("等待超时")
        if not mute_time.isdigit():
            continue
        break
    else:
        await mute_sb_cmd.finish("输入失败")

    mute_time = int(mute_time)

    if mute_time > 1440:
        await mute_sb_cmd.finish("你好恶毒啊！")

    await bot.set_group_ban(group_id=event.group_id, user_id=qq, duration=mute_time * 60)


def check_mute(event: GroupMessageEvent):
    message = event.get_message()
    message_length = len(message)
    if message_length == 1:
        msg = message.extract_plain_text().strip()
        return re.fullmatch(r"mute\s*all\s*(\d+)", msg)
    if message_length == 3:
        try:
            return (
                message[0].data["text"].strip() == "mute"
                and message[1].type == "at"
                and message[2].data["text"].strip().isdigit()
            )
        except KeyError:
            return False
    return False


mute_cmd = on_command(cmd="mute", rule=check_mute, permission=permit_roles)


@mute_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    message = event.get_message()
    message_length = len(message)
    if message_length == 3:
        qq = message[1].data["qq"]
        time = int(message[2].data["text"])
        await bot.set_group_ban(group_id=event.group_id, user_id=qq, duration=int(time) * 60)
    if message_length == 1:
        match = re.fullmatch(r"mute\s*all\s*(\d+)", message.extract_plain_text().strip())
        await bot.set_group_whole_ban(group_id=event.group_id, enable=(int(match.group(1)) > 0))


mute_voting_cmd = on_command(cmd="mute voting")
lock = Lock()


@mute_voting_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, arg: Message = CommandArg()):
    global switch, lock
    if not (mute_time := arg.extract_plain_text().strip()).isdigit():
        await mute_voting_cmd.finish("禁言时间不合法")

    switch = False
    await mute_voting_cmd.send("已开启禁言投票")
    await mute_voting_cmd.send("请@你要禁言的人或输入其QQ号")

    @waiter(waits=["message"], keep_session=False)
    async def check(event: GroupMessageEvent):
        message = [ms for ms in event.get_message() if not (ms.type == "text" and ms.data["text"].strip() == "")]
        if len(message) == 1 and message[0].type == "at":  # at消息
            return event.user_id, int(message[0].data["qq"])
        if len(message) == 1 and message[0].type == "text" and (m0 := message[0].data["text"].strip()).isdigit():  # 纯数字指定
            return event.user_id, int(m0)
        return event.user_id, -1  # 非投票消息

    voted_members: list[int] = []
    wait_for_mute: dict[int, set[int]] = {}
    msg_count_since_last_vote = 0

    async for res in check(timeout=20):
        if not res:  # 长时间没人发
            switch = True
            await mute_voting_cmd.finish("投票超时结束")

        user_id, qq = res
        if msg_count_since_last_vote > config.msg_count_max_last_vote:  # 发言长期未涉及投票
            switch = True
            await mute_voting_cmd.finish("投票超时结束")

        if qq == -1:  # 如果不是投票消息
            msg_count_since_last_vote += 1
            continue

        if qq == 0:  # 如果是老版本QQ或Tim，检测不到@
            msg_count_since_last_vote += 1
            await mute_voting_cmd.send("老版本QQ以及Tim用户请使用QQ号投票")
            continue
        
        async with lock:
            if user_id not in voted_members:  # 如果成员没有参与过投票
                voted_members.append(user_id)
                msg_count_since_last_vote = 0  # 清空投票间隙

                if qq not in wait_for_mute:
                    wait_for_mute[qq] = set()

                wait_for_mute[qq].add(user_id)
                count = len(wait_for_mute[qq])  # 票数

                if count >= config.voting_member_count:  # 被投票成员达到指定票数
                    await bot.set_group_ban(group_id=event.group_id, user_id=qq, duration=int(mute_time) * 60)
                    switch = True
                    # 发送投票统计消息
                    res_msg = (
                        MessageSegment.at(qq)
                        + MessageSegment.text("请记住, 这些人投票禁言了你!\n")
                        + at_members(wait_for_mute[qq])
                    )
                    await mute_voting_cmd.send(res_msg)
                    await mute_voting_cmd.finish(f"已禁言{qq} {mute_time}分钟")
                msg = MessageSegment.at(user_id) + MessageSegment.text(f" 已投{qq}一票，目前得票{count}")
                await mute_voting_cmd.send(msg)
            else:
                msg_count_since_last_vote += 1
                await mute_voting_cmd.send(MessageSegment.at(user_id) + MessageSegment.text(" 你已经投过票啦!"))


def at_members(members: set[int]) -> Message:
    return Message([MessageSegment.at(member) for member in members])
