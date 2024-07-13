import random
import string
from typing import Any
from nonebot import require, get_driver
from datetime import datetime

from json import loads, dumps
from pathlib import Path
from nonebot.adapters.onebot.v11 import Bot
from aiofiles import open as aopen

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402

driver = get_driver()

muted_list_dict: dict[str, dict[str, int]] = {}
"""存储被禁言的用户
{
    "group_id:user_id": {
        "count": int,
        "time": int
    }
    ...
}
"""

mute_history: list[dict[str, int]] = []
"""禁言历史
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

schedule_dict: dict[str, dict[str, Any]] = {}
"""定时任务列表
{
    "schedule_id": {
        "group_id": int,
        "user_id": int,
        "period": int,
        "start_hour": str,
        "start_minute": str
    },
    ...
}
"""


ban_file: Path = store.get_data_file("russian_ban", "ban.json")
history_file: Path = store.get_data_file("russian_ban", "history.json")
schedule_file: Path = store.get_data_file("russian_ban", "schedule.json")

# 读取持久化的数据
if ban_file.exists():
    muted_list_dict = loads(t) if (t := ban_file.read_text()) else {}
if history_file.exists():
    mute_history = loads(t) if (t := history_file.read_text()) else []
if schedule_file.exists():
    schedule_dict = loads(t) if (t := schedule_file.read_text()) else {}


@driver.on_bot_connect
async def _(bot: Bot):
    """在Bot连接成功后执行对应操作

    Args:
        bot (Bot): bot对象
    """
    for job_id, job in schedule_dict.items():
        await add_schedule(
            bot=bot,
            user_id=job["user_id"],
            group_id=job["group_id"],
            period=job["period"],
            hour=job["start_hour"],
            minute=job["start_minute"],
            job_id=job_id,
        )


async def save_mute(muted_list_dict: dict[str, dict[str, int]] = {}, mute_history: list[dict[str, int]] = []):
    """保存禁言数据

    Args:
        muted_list_dict (dict[str, dict[str, int]], optional): 禁言列表. Defaults to {}.
        mute_history (list[dict[str, int]], optional): 禁言历史. Defaults to [].
    """
    async with aopen(ban_file, mode="w") as fp:
        await fp.write(dumps(muted_list_dict, indent=4))
    async with aopen(history_file, "w") as fp:
        await fp.write(dumps(mute_history, indent=4))


async def save_schedule(schedule_list: list[dict[str, Any]] = {}):
    """保存定时任务

    Args:
        schedule_list (list[dict[str, Any]], optional): 定时任务. Defaults to {}.
    """
    async with aopen(schedule_file, mode="w") as fp:
        await fp.write(dumps(schedule_list, indent=4))


require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402


@scheduler.scheduled_job("cron", hour="0", id="clear_record")
async def clear_mute_list_n_history():
    """清空禁言列表与历史记录
    """
    global muted_list_dict, mute_history
    new_muted_list_dict = {k: v for k, v in muted_list_dict.items() if v["time"] > int(datetime.now().timestamp())}
    muted_list_dict = new_muted_list_dict
    mute_history.clear()
    await save_mute()


async def ban_reserve(bot: Bot, user_id: int, group_id: int, time: int, job_id: str):
    """定时任务：在某时间点禁言某人多少分钟

    Args:
        user_id (int): 将被禁言的用户
        group_id (int): 用户所在的群组
        hour (int): 时刻
        minute (int): 分刻
        time (int): 禁言时间
    """
    await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=time * 60)
    scheduler.remove_job(job_id=job_id)
    schedule_dict.pop(job_id, {})
    await save_schedule(schedule_dict)


def generate_random_string(length: int) -> str:
    """生成指定长度的随机字符串

    Args:
        length (int): 长度

    Returns:
        str: 结果
    """
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


async def add_schedule(
    *,
    bot: Bot,
    user_id: int,
    group_id: int,
    period: int,
    hour: str,
    minute: str,
    job_id: str = generate_random_string(10),
):
    """添加一个禁言定时任务

    Args:
        bot (Bot): bot对象
        user_id (int): 用户id
        group_id (int): 群组id
        period (int): 禁言时间
        hour (str): 禁言时刻
        minute (str): 禁言分刻
        job_id (str, optional): 任务id. Defaults to generate_random_string(10).
    """
    scheduler.add_job(
        ban_reserve, "cron", hour=hour, minute=minute, id=job_id, args=[bot, user_id, group_id, period, job_id]
    )
    schedule_dict.update(
        {job_id: {"group_id": group_id, "user_id": user_id, "period": period, "start_hour": hour, "start_minute": minute}}
    )
    await save_schedule(schedule_dict)
