import random
import string
from nonebot import require
from datetime import datetime

from json import loads, dumps
from pathlib import Path
from nonebot.adapters.onebot.v11 import Bot
from aiofiles import open as aopen

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402

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

ban_file: Path = store.get_data_file("russian_ban", "ban.json")
history_file: Path = store.get_data_file("russian_ban", "history.json")

# read ban file to list
if ban_file.exists():
    muted_list_dict = loads(t) if (t := ban_file.read_text()) else {}
if history_file.exists():
    mute_history = loads(t) if (t := history_file.read_text()) else {}


async def save(muted_list_dict: dict[str, dict[str, int]], mute_history: list[dict[str, int]]):
    """save ban list"""
    async with aopen(ban_file, mode='w') as fp:
        await fp.write(dumps(muted_list_dict, indent=4))
    async with aopen(history_file, 'w') as fp:
        await fp.write(dumps(mute_history, indent=4))


require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402


@scheduler.scheduled_job("cron", hour="0", id="clear_record")
async def clear_mute_list_n_history():
    global muted_list_dict, mute_history
    new_muted_list_dict = {k: v for k, v in muted_list_dict.items() if v["time"] > int(datetime.now().timestamp())}
    muted_list_dict = new_muted_list_dict
    mute_history.clear()
    await save(muted_list_dict, mute_history)


async def ban_reserve(bot: Bot, user_id: int, group_id: int, time: int, job_id: str):
    """reserve ban somebody

    Args:
        user_id (int): will be ban user
        group_id (int): user in group
        hour (int): hour
        minute (int): minute
        time (int): ban time
    """
    await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=time * 60)
    scheduler.remove_job(job_id=job_id)


async def add_schedule(*, bot: Bot, user_id: int, group_id: int, time: int, hour: str, minute: str):
    """add schedule"""
    job_id = generate_random_string(10)
    scheduler.add_job(
        ban_reserve, "cron", hour=hour, minute=minute, id=job_id, args=[bot, user_id, group_id, time, job_id]
    )


def generate_random_string(length: int) -> str:
    result = "".join(random.choices(string.ascii_letters + string.digits, k=length))
    return result
