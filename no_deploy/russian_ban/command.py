import re
from .schedule import save_mute, add_schedule, remove_schedule, muted_list_dict
from .decorator import switch_depend, mute_sb_stop_runpreprocessor, negate_return_value
from .rule import check_mute_sb
from nonebot import on_command, logger, on_notice
from nonebot.rule import to_me
from nonebot.matcher import Matcher
from nonebot.params import CommandArg, CommandStart
from nonebot.message import run_preprocessor, event_preprocessor
from sqlalchemy import select
from nonebot_plugin_orm import get_session


from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    PrivateMessageEvent,
    PokeNotifyEvent,
    MessageEvent,
    Message,
    MessageSegment,
)
from nonebot_plugin_waiter import waiter
from random import choices, choice
from .config import config
from common.struct import ExpirableDict
from common.permission import admin_permission
from .model import ScheduleBanJob
from asyncio import Lock


switch = True
"""是否开启随机禁言
"""

ignoreIds: set[int] = set()

random_mute_dict = {
    0: 128,
    1: 64,
    2: 32,
    5: 16,
    10: 8,
    30: 4,
    60: 2,
}
"""随机禁言时间权重
"""

user_id_nickname_dict: dict[int, str] = {}
"""用户ID与昵称对应关系
"""


@event_preprocessor
async def save_user_id_nickname(event: GroupMessageEvent):
    global user_id_nickname_dict
    """保存用户ID与昵称对应关系

    Args:
        event (GroupMessageEvent): 群组消息事件
    """
    user_id_nickname_dict |= {event.user_id: event.sender.card or event.sender.nickname or ""}
    logger.debug(user_id_nickname_dict)


# @run_preprocessor
@switch_depend(dependOn=[lambda *args, **kwargs: switch, negate_return_value(check_mute_sb)], ignoreIds=ignoreIds)
async def random_mute(bot: Bot, event: GroupMessageEvent, cs: str = CommandStart()):
    """触发指令时，对某人进行随机禁言

    Args:
        bot (Bot): bot 对象
        event (Event): 群组消息事件
    """
    global switch, random_mute_dict, muted_list_dict
    # 如果处于关闭状态，则不检测
    # if event.sender.role in ["admin", "owner"]:
    #     return
    # 检查这个人是否已被禁言过
    keys = list(random_mute_dict.keys())
    weights = list(random_mute_dict.values())
    v = muted_list_dict.get(f"{event.group_id}:{event.user_id}", {"time": 0, "count": 0})
    # 如果这个人被禁言过，则增加被禁言的权重，减少不被禁言的权重
    if config.increase_probability:
        weights[0] >>= v["count"]
        weights[-1] <<= v["count"]
    # 如果这个人被禁言过，则安装被禁言次数增加每档禁言时间
    if config.increase_duration:
        keys = [i << v["count"] for i in keys]
    [min_res] = choices(keys, weights=weights, k=1)
    min_res = min_res * 60
    if min_res == 0:
        return
    await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=min_res)
    logger.info(f"{event.user_id}在{event.group_id}于{event.time}时被禁言{min_res}秒")
    v["time"] = event.time + min_res
    v["count"] += 1
    muted_list_dict[f"{event.group_id}:{event.user_id}"] = v
    await save_mute(muted_list_dict)


un_mute_all = on_command(cmd="mute clear", aliases={"mc"}, permission=admin_permission)


# @un_mute_all.handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher):
    """解除所有禁言（因触发命令而被禁言的用户，其他情况下被禁言的用户无法解除）

    Args:
        bot (Bot): bot对象
        event (MessageEvent): 消息事件
    """
    global muted_list_dict
    for key, value in muted_list_dict.items():
        [group_id, user_id] = key.split(":")
        # 如果该成员仍然处于禁言状态
        if value["time"] > event.time:
            # 如果消息事件是群组消息事件，则解除对应群组的所有禁言
            if isinstance(event, GroupMessageEvent) and str(event.group_id) == group_id:
                await bot.set_group_ban(group_id=int(group_id), user_id=int(user_id), duration=0)
            # 如果消息事件是私聊消息事件，则解除所有禁言
            if isinstance(event, PrivateMessageEvent):
                await bot.set_group_ban(group_id=int(group_id), user_id=int(user_id), duration=0)
    # 如果消息事件是群组消息事件，则清空该群组禁言列表
    if isinstance(event, GroupMessageEvent):
        muted_list_dict = {k: v for k, v in muted_list_dict.items() if k.split(":")[0] != str(event.group_id)}
    else:
        # 如果消息事件是私聊消息事件，则清空所有禁言列表
        muted_list_dict.clear()
    await save_mute(muted_list_dict)
    await matcher.finish("已解除所有禁言")


query = on_command(cmd="mute query", aliases={"mq"}, permission=admin_permission)


# @query.handle()
async def _(event: MessageEvent, matcher: Matcher):
    """禁言列表查询（因触发命令而被禁言的用户）

    Args:
        event (MessageEvent): 消息事件
    """
    global muted_list_dict
    members = dict_group_by_group_id(muted_list_dict)
    if isinstance(event, GroupMessageEvent):
        members_group = members.get(str(event.group_id))
        if not members_group:
            await matcher.finish("当前没有禁言名单")
        else:
            msg = "当前禁言名单："
            for key, value in members_group.items():
                msg += f"\n{user_id_nickname_dict.get(int(key), key)} 禁言次数：{value['count']}"
            await matcher.finish(msg)
    else:
        if not members:
            await matcher.finish("当前没有禁言名单")
        else:
            msg = "当前禁言名单："
            for group_id, value in members.items():
                msg += f"\n群组: {group_id}"
                for user_id, info in value.items():
                    msg += f"\n{user_id_nickname_dict.get(int(user_id), user_id)} 禁言次数: {info['count']}"
            await matcher.finish(msg)


def dict_group_by_group_id(members: dict[str, dict[str, int]]) -> dict[str, dict[str, dict[str, int]]]:
    """将禁言列表按群组id进行分组

    Args:
        members (dict[str : dict[str, int]]): 禁言列表
    Returns:
        dict[str, dict[str : dict[str, int]]]: 按群组id分组后的禁言列表
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


mute_sb_cmd = on_command(cmd="mute sb", aliases={"msb"})


# @mute_sb_cmd.handle()
@mute_sb_stop_runpreprocessor(ignoreIds=ignoreIds)
async def mute_sb(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """禁言某人

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
    """
    await matcher.send("请输入QQ号")

    @waiter(waits=["message"], keep_session=True)
    async def check_qq(event: GroupMessageEvent) -> str:
        """返回QQ号

        Args:
            event (GroupMessageEvent): 群组消息事件

        Returns:
            str: 合规的QQ号
        """
        ms = event.get_message()[0]
        return str(ms.data["qq"]) if ms.type == "at" else str(ms.data["text"])

    async for qq in check_qq(timeout=20, retry=5, prompt="输入错误，请@某人或输入qq号。剩余次数: {count}"):
        if qq is None:
            await matcher.finish("等待超时")
        if not qq.isdigit():
            continue
        break
    else:
        await matcher.finish("输入失败")
    qq = int(qq)
    await matcher.send("请输入禁言时间，单位分钟")

    @waiter(waits=["message"], keep_session=True)
    async def check_time(event: GroupMessageEvent) -> str:
        """返回禁言时长

        Args:
            event (GroupMessageEvent): 群组消息事件

        Returns:
            str: 禁言时长
        """
        return event.get_plaintext()

    async for mute_time in check_time(timeout=20, retry=5, prompt="输入错误，请输入数字。剩余次数: {count}"):
        if mute_time is None:
            await matcher.finish("等待超时")
        if not mute_time.isdigit():
            continue
        break
    else:
        await matcher.finish("输入失败")

    mute_time = int(mute_time)

    random_user_id: list[int] = [event.user_id, qq]

    if mute_time > 1440:
        await matcher.finish("你好恶毒啊！")

    await bot.set_group_ban(group_id=event.group_id, user_id=choice(random_user_id), duration=mute_time * 60)


mute_cmd = on_command(cmd="mute", permission=admin_permission)


@mute_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """mute @sb st

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
    """
    message = event.get_message()
    message_length = len(message)
    if message_length == 3:
        qq = message[1].data["qq"]
        time = int(message[2].data["text"])
        await bot.set_group_ban(group_id=event.group_id, user_id=qq, duration=int(time) * 60)
    if message_length == 1:
        match = re.fullmatch(r"mute\s*all\s*(\d+)", message.extract_plain_text().strip())
        if match:
            await bot.set_group_whole_ban(group_id=event.group_id, enable=(int(match.group(1)) > 0))


mute_voting_cmd = on_command(cmd="mute voting", aliases={"mv"})
lock = Lock()


@mute_voting_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher, arg: Message = CommandArg()):
    """禁言投票

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
        arg (Message, optional): 禁言时间. Defaults to CommandArg().
    """
    global switch, lock
    if not (mute_time := arg.extract_plain_text().strip()).isdigit():
        await matcher.finish("禁言时间不合法")

    if int(mute_time) > 43200:
        await matcher.finish("禁言时间超过最大限度")

    # 在禁言投票期间，关闭命令触发检测禁言
    switch = False

    max_count = len(mute_time) if int(mute_time) > 0 else 3

    await matcher.send(f"已开启禁言投票，投票成功票数为{max_count}")
    await matcher.send("请@你要禁言的人或输入其QQ号")

    @waiter(waits=["message"], keep_session=False)
    async def check(event: GroupMessageEvent) -> tuple[int, int]:
        """检测消息是否为@sb或qq

        Args:
            event (GroupMessageEvent): 群组消息事件

        Returns:
            tuple[int, int]: 触发事件的用户id, 被投票的用户id
        """
        message = [ms for ms in event.get_message() if not (ms.type == "text" and ms.data["text"].strip() == "")]
        if len(message) == 1 and message[0].type == "at":  # at消息
            return event.user_id, int(message[0].data["qq"])
        if (
            len(message) == 1 and message[0].type == "text" and (m0 := message[0].data["text"].strip()).isdigit()
        ):  # 纯数字指定
            return event.user_id, int(m0)
        return event.user_id, -1  # 非投票消息

    voted_members: list[int] = []
    wait_for_mute: dict[int, set[int]] = {}
    msg_count_since_last_vote = 0

    async for res in check(timeout=20):
        if not res:  # 长时间没人发
            switch = True
            await matcher.finish("投票超时结束")

        user_id, qq = res
        if msg_count_since_last_vote > config.msg_count_max_last_vote:  # 发言长期未涉及投票
            switch = True
            await matcher.finish("投票超时结束")

        if qq == -1:  # 如果不是投票消息
            msg_count_since_last_vote += 1
            continue

        async with lock:
            if user_id not in voted_members:  # 如果成员没有参与过投票
                voted_members.append(user_id)
                msg_count_since_last_vote = 0  # 清空投票间隙

                if qq not in wait_for_mute:
                    wait_for_mute[qq] = set()

                wait_for_mute[qq].add(user_id)
                count = len(wait_for_mute[qq])  # 票数

                if count >= max_count:  # 被投票成员达到指定票数
                    await bot.set_group_ban(group_id=event.group_id, user_id=qq, duration=int(mute_time) * 60)
                    switch = True
                    # 发送投票统计消息
                    res_msg = (
                        MessageSegment.at(qq)
                        + MessageSegment.text(f"请记住, 这些人投票{'禁言' if int(mute_time) > 0 else '解禁'}了你!\n")
                        + at_members(wait_for_mute[qq])
                    )
                    await matcher.send(res_msg)
                    if int(mute_time) > 0:
                        await matcher.finish(f"已禁言 {user_id_nickname_dict.get(qq, qq)} {mute_time}分钟")
                    else:
                        await matcher.finish(f"已解禁 {user_id_nickname_dict.get(qq, qq)}")
                msg = MessageSegment.at(user_id) + MessageSegment.text(
                    f" 已投 {user_id_nickname_dict.get(qq, qq)} 一票，目前得票{count}"
                )
                await matcher.send(msg)
            else:
                msg_count_since_last_vote += 1
                await matcher.send(MessageSegment.at(user_id) + MessageSegment.text(" 你已经投过票啦!"))


def at_members(members: set[int]) -> Message:
    """拼接at消息

    Args:
        members (set[int]): 用户id集合

    Returns:
        Message: 所有的@消息
    """
    return Message([MessageSegment.at(member) for member in members])


mute_schedule_cmd = on_command(cmd="mute schedule", aliases={"ms"}, permission=admin_permission)


def split_event_args(msg: Message) -> tuple[int, int, str, str]:
    """分解消息

    Args:
        msg (Message): 消息

    Returns:
        tuple[int, int, str, str]: qq, period, hour, minute
    """
    qq = int(msg[1].data.get("qq", ""))
    pattern = r"^(\d+)\s*at\s*([01]?\d|2[0-3])(:[0-5]?\d)?$"
    match = re.match(pattern, msg[2].data.get("text", "").strip())
    if match: 
        period = int(match.group(1))
        hour = str(match.group(2))
        minute = str(match.group(3)[1:]) if match.group(3) else "0"
        return qq, period, hour, minute
    else:
        return -1, -1, "", ""

@mute_schedule_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """在某时某分让某人被禁言某段时间

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
    """
    message = event.get_message()
    qq, period, hour, minute = split_event_args(message)
    group_id = event.group_id
    await add_schedule(bot=bot, group_id=group_id, user_id=qq, period=period, hour=int(hour), minute=int(minute))
    msg = f"已设置{user_id_nickname_dict.get(qq, qq)}在{hour}:{minute:0>2}被禁言{period}分钟"
    logger.info(msg)
    await bot.send_group_msg(group_id=group_id, message=msg)


remove_schedule_cmd = on_command(cmd="remove schedule", aliases={"rms"}, permission=admin_permission)


@remove_schedule_cmd.handle()
async def _(matcher: Matcher, arg: Message = CommandArg()):
    """移除指定定时任务

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
    """
    job_ids = [job_id for job_id in arg.extract_plain_text().strip().split(" ") if job_id != ""]
    for job_id in job_ids:
        await remove_schedule(job_id=job_id)
        await matcher.send(f"已移除定时任务 {job_id} ")


list_schedule_cmd = on_command(cmd="list schedule", aliases={"lss"}, permission=admin_permission)


def get_group_id(event: GroupMessageEvent) -> int:
    return event.group_id


@list_schedule_cmd.handle()
async def _(event: GroupMessageEvent, matcher: Matcher):
    """查看定时任务

    Args:
        event (GroupMessageEvent): 群组消息事件
    """
    group_id = event.group_id
    session = get_session()
    async with session.begin():
        jobs = (
            (await session.execute(select(ScheduleBanJob).where(ScheduleBanJob.group_id == group_id))).scalars().all()
        )
        if len(jobs) > 0:
            msg = f"当前群组 {group_id} 的定时任务列表："
            for job in jobs:
                msg += f"\n任务 {job.job_id}：{user_id_nickname_dict.get(int(job.user_id), job.user_id)} 在 {job.start_hour}:{job.start_minute:02} 被禁言 {job.period} 分钟"
        else:
            msg = "当前群组没有定时任务"
        await matcher.finish(msg)


mock_mute_dict: dict[int, ExpirableDict[str, int]] = {}
"""虚假禁言列表
"""

mock_mute_sb_cmd = on_command(cmd="mock mute", aliases={"mm"}, permission=admin_permission)


@mock_mute_sb_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher, arg: Message = CommandArg()):
    """让某人在接下来的某段时间每次发言均会被撤回

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
    """
    global mock_mute_dict
    group_id = event.group_id
    mock_mute_dict_group = mock_mute_dict.get(group_id, ExpirableDict(str(group_id)))
    qq = arg[0].data.get("qq")
    period = int(arg[1].data.get("text") or 0)
    mock_mute_dict_group.set(str(qq), 1, period * 60)
    mock_mute_dict.update({group_id: mock_mute_dict_group})
    message = [MessageSegment.at(int(qq or 0)), MessageSegment.text(f" 你已被管理员禁言{period}分钟")]
    await matcher.finish(Message(message))


mock_mute_sb_delete_cmd = on_command(cmd="mock mute delete", aliases={"mmd"}, permission=admin_permission)


@mock_mute_sb_delete_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher, arg: Message = CommandArg()):
    global user_id_nickname_dict
    """移除某人的模拟禁言

    Args:
        bot (Bot): bot 对象
        event (GroupMessageEvent): 群组消息事件
    """
    global mock_mute_dict
    group_id = event.group_id
    mock_mute_dict_group = mock_mute_dict.get(group_id, ExpirableDict(str(group_id)))
    qq = arg[0].data.get("qq")
    if mock_mute_dict_group.get(str(qq)) is not None:
        mock_mute_dict_group.delete(str(qq))
        mock_mute_dict.update({group_id: mock_mute_dict_group})
        message = [MessageSegment.at(int(qq or 0)), MessageSegment.text(" 你已被管理员解除禁言")]
        await matcher.finish(Message(message))
    else:
        message = MessageSegment.text(f"{user_id_nickname_dict.get(int(qq or 0), str(qq))} 没有被禁言")
        await matcher.finish(Message(message))


@on_notice(rule=to_me()).handle()
async def _(bot: Bot, event: PokeNotifyEvent, matcher: Matcher):
    """收到戳一戳事件，如果用户处于禁言状态，则返回其剩余的解禁时间"""
    group_id = event.group_id
    mock_mute_dict_group = mock_mute_dict.get(group_id or 0, ExpirableDict(str(group_id)))
    qq = event.user_id
    if (ttl := mock_mute_dict_group.ttl(str(qq))) > 0:
        message = [MessageSegment.at(int(qq)), MessageSegment.text(f" 你剩余禁言时间还有 {ttl//60}:{ttl%60:02}")]
        await matcher.finish(Message(message))


@event_preprocessor
async def delete_message_judge(bot: Bot, event: GroupMessageEvent):
    """判断某个人的消息是否应该撤回

    Args:
        event (GroupMessageEvent): 群组消息事件
    """
    global mock_mute_dict
    group_id = event.group_id
    user_id = event.user_id
    mock_mute_dict_group = mock_mute_dict.get(group_id, ExpirableDict(str(group_id)))
    if mock_mute_dict_group.ttl(str(user_id)) > 0:
        await bot.delete_msg(message_id=event.message_id)
