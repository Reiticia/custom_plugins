import random
import string
from nonebot import logger, get_driver
from datetime import datetime

from json import loads, dumps
from pathlib import Path
from nonebot.adapters.onebot.v11 import Bot
from aiofiles import open as aopen

from sqlalchemy import select, delete
from .model import ScheduleBanJob

from nonebot_plugin_orm import get_session

import nonebot_plugin_localstore as store 

from nonebot_plugin_apscheduler import scheduler

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

ban_file: Path = store.get_data_file("russian_ban", "ban.json")

# 读取持久化的数据
if ban_file.exists():
    muted_list_dict = loads(t) if (t := ban_file.read_text()) else {}


@driver.on_bot_connect
async def _(bot: Bot):
    """在Bot连接成功后执行对应操作

    Args:
        bot (Bot): bot对象
    """
    logger.debug(f"{bot.self_id} login")
    session = get_session()
    async with session.begin():
        jobs = (await session.execute(select(ScheduleBanJob))).scalars().all()
        for job in jobs:
            scheduler.add_job(
                ban_reserve,
                "cron",
                hour=job.start_hour,
                minute=job.start_minute,
                id=job.job_id,
                args=[bot, job.user_id, job.group_id, job.period, job.job_id, job.once],
            )


async def save_mute(muted_list_dict: dict[str, dict[str, int]] = {}):
    """保存禁言数据

    Args:
        muted_list_dict (dict[str, dict[str, int]], optional): 禁言列表. Defaults to {}.
    """
    async with aopen(ban_file, mode="w") as fp:
        await fp.write(dumps(muted_list_dict, indent=4))



@scheduler.scheduled_job("cron", hour="0", id="clear_record")
async def clear_mute_list_n_history():
    """清空禁言列表与历史记录"""
    global muted_list_dict
    new_muted_list_dict = {k: v for k, v in muted_list_dict.items() if v["time"] > int(datetime.now().timestamp())}
    muted_list_dict = new_muted_list_dict
    await save_mute(muted_list_dict)


async def ban_reserve(bot: Bot, user_id: int, group_id: int, time: int, job_id: int, once: bool):
    """定时任务：在某时间点禁言某人多少分钟

    Args:
        user_id (int): 将被禁言的用户
        group_id (int): 用户所在的群组
        hour (int): 时刻
        minute (int): 分刻
        time (int): 禁言时间
        once (bool): 是否为一次性定时任务
    """
    await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=time * 60)
    if once:
        await remove_schedule(job_id=job_id)
        # 删数据库
        session = get_session()
        async with session.begin():
            await session.execute(delete(ScheduleBanJob).where(ScheduleBanJob.job_id == job_id))
        await session.commit()


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
    hour: int,
    minute: int,
    once: bool = True,
    job_id: str = None,
):
    """添加一个禁言定时任务

    Args:
        bot (Bot): bot对象
        user_id (int): 用户id
        group_id (int): 群组id
        period (int): 禁言时间
        hour (int): 禁言时刻
        minute (int): 禁言分刻
        once (bool): 是否一次性任务
        job_id (str, optional): 任务id. Defaults to None.
    """
    job_id = job_id if job_id else generate_random_string(10)

    scheduler.add_job(
        ban_reserve, "cron", hour=hour, minute=minute, id=job_id, args=[bot, user_id, group_id, period, job_id, once]
    )

    job = ScheduleBanJob(
        job_id=job_id,
        group_id=group_id,
        user_id=user_id,
        period=period,
        start_hour=hour,
        start_minute=minute,
        once=once,
    )

    # 写数据库
    session = get_session()
    async with session.begin():
        session.add(job)
    await session.commit()


async def remove_schedule(*, job_id: str):
    """删除一个禁言定时任务

    Args:
        job_id (str, optional): 任务id
        schedule_dict (dict[str, dict[str, Any]]): 任务字典
    """
    scheduler.remove_job(job_id=job_id)
    # 删数据库
    session = get_session()
    async with session.begin():
        await session.execute(delete(ScheduleBanJob).where(ScheduleBanJob.job_id == job_id))
    await session.commit()
