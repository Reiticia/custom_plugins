from datetime import datetime
from nonebot import get_plugin_config, on_command, require
from nonebot.params import Arg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.message import run_preprocessor
from nonebot.adapters.onebot.v11 import (
    Bot,
    GROUP_OWNER,
    GroupMessageEvent,
    PrivateMessageEvent,
    MessageEvent,
    Message,
)
from random import choices
from loguru import logger

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="russian_ban",
    description="",
    usage="mute clear 解除所有禁言\n mute query 查询禁言列表\n mute history 查询机器人禁言历史记录",
    config=Config,
)

config = get_plugin_config(Config)

switch = True
"""ban switch
"""

random_mute_dict = {0: 128, 1: 64, 2: 32, 5: 16, 10: 8, 30: 4, 60: 2}
"""random ban dict
"""

muted_list_dict: dict[str, dict[str, int]] = {}
"""Ban User List Structure
{
    "group_id:user_id": {
        "count": int,
        "time": int
    }
    ...
}
"""

mute_history: list[dict[str, int]] = []
"""mute history
[
    {
        "group_id": int,
        "user_id": int,
        "start_time": int,
        "duration": int
    },
    ...
]
"""


@run_preprocessor
async def random_mute(bot: Bot, event: GroupMessageEvent):
    """random ban someone

    Args:
        bot (Bot): bot object
        event (Event): group message event
    """
    global switch, random_mute_dict, muted_list_dict
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
        await bot.set_group_ban(
            group_id=event.group_id, user_id=event.user_id, duration=min_res
        )
        mute_history.append(
            {
                "group_id": event.group_id,
                "user_id": event.user_id,
                "start_time": event.time,
                "duration": min_res / 60,
            }
        )
        logger.info(
            f"{event.user_id}在{event.group_id}于{event.time}时被禁言{min_res}秒"
        )
        v["time"] = event.time + min_res
        v["count"] += 1
        muted_list_dict[f"{event.group_id}:{event.user_id}"] = v


permit_roles = GROUP_OWNER | SUPERUSER

un_mute_all = on_command(cmd="mute clear", permission=permit_roles)


@un_mute_all.handle()
async def _(bot: Bot, event: MessageEvent):
    global muted_list_dict
    for (
        key,
        value,
    ) in muted_list_dict.items():
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
        muted_list_dict = {
            k: v
            for k, v in muted_list_dict.items()
            if k.split(":")[0] != str(event.group_id)
        }
    else:
        muted_list_dict.clear()
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


def lst_group_by_group_id(
    history: list[dict[str, int]],
) -> dict[int, list[dict[str, int]]]:
    """历史记录分组

    Args:
        history (list[dict[str, int]]): 历史记录
    Returns:
        dict[int, list[dict[str, int]]]: 按group_id分组后的结果
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


def dict_group_by_group_id(
    members: dict[str : dict[str, int]],
) -> dict[str, dict[str : dict[str, int]]]:
    """字典分组

    Args:
        members (dict[str : dict[str, int]]): 要分组的members字典
    Returns:
        dict[str, dict[str : dict[str, int]]]: 按group_id分组后的结果
    """
    res: dict[str, dict[str : dict[str, int]]] = {}
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


require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402


@scheduler.scheduled_job("cron", hour="0", id="clear_record")
async def clear_mute_list_n_history():
    global muted_list_dict, mute_history
    new_muted_list_dict = {}
    for k, v in muted_list_dict.items():
        if v["time"] > int(datetime.now().timestamp()):
            new_muted_list_dict[k] = v
    muted_list_dict = new_muted_list_dict
    mute_history.clear()


mute_sb_cmd = on_command(cmd="mute sb", permission=permit_roles)


@mute_sb_cmd.handle()
@mute_sb_cmd.got("qq", prompt="请输入QQ号")
@mute_sb_cmd.got("time", prompt="请输入禁言时间")
async def mute_sb(
    bot: Bot, event: GroupMessageEvent, qq: Message = Arg(), time: Message = Arg()
):
    if qq[0].type == "at":
        qq_num = qq[0].data["qq"]
    else:
        try:
            qq_num = int(qq[0].data["text"])
        except ValueError:
            if qq[0].data["text"] == "stop":
                await mute_sb_cmd.finish()
            await mute_sb_cmd.reject_arg("qq", "请输入正确的QQ号")
    try:
        time = int(time[0].data["text"]) * 60
    except ValueError:
        if time[0].data["text"] == "stop":
            await mute_sb_cmd.finish()
        await mute_sb_cmd.reject_arg("time", "请输入正确的禁言时间")
    await bot.set_group_ban(group_id=event.group_id, user_id=qq_num, duration=time)
    await mute_sb_cmd.finish()
