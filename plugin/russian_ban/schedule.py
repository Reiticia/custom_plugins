from nonebot import require
from datetime import datetime

from json import loads, dumps
from pathlib import Path

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
    muted_list_dict = loads(ban_file.read_text())
if history_file.exists():
    mute_history = loads(history_file.read_text())

def save():
    """save ban list"""
    ban_file.write_text(dumps(muted_list_dict))
    history_file.write_text(dumps(mute_history))


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
    save()

