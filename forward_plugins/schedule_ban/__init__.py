import json
from typing import TypedDict
from nonebot import get_bot, get_plugin_config, logger, require, get_driver
from nonebot.adapters import Bot
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_uninfo")

from nonebot_plugin_alconna import Alconna, Args, At, Option, Subcommand, on_alconna, Match, Query
from nonebot_plugin_uninfo import Uninfo
from nonebot_plugin_apscheduler import scheduler
import nonebot_plugin_localstore as store

from .config import Config
from common.permission import owner_permission
from common import generate_random_string

__plugin_meta__ = PluginMetadata(
    name="schedule_ban",
    description="",
    usage="",
    config=Config,
)


class BanTask(TypedDict):
    """单个禁言任务"""

    id: str
    """任务ID"""
    user_id: str
    """用户ID"""
    group_id: str
    """群组ID"""
    time: int
    """禁言时长"""
    once: bool
    """是否一次性任务"""
    cron: str
    """cron表达式"""


config = get_plugin_config(Config)


cmd = on_alconna(
    Alconna(
        "禁言",
        Subcommand(
            "添加",
            Args["user", At],
            Args["time", int],
        ),
        Subcommand("列表"),
        Subcommand(
            "移除",
            Args["id", str],
        ),
        Option("-o|--once", Args["val", bool]),
        Option("-c|--cron", Args["val", str]),
        Option("-s|--second", Args["val", str]),
        Option("-m|--minute", Args["val", str]),
        Option("-H|--hour", Args["val", str]),
        Option("-d|--day", Args["val", str]),
        Option("-M|--month", Args["val", str]),
        Option("-w|--week", Args["val", str]),
        Option("-y|--year", Args["val", str]),
    ),
    response_self=True,
    permission=owner_permission,
)

_SCHEDULE_BAN_PROFILE = store.get_config_dir("schedule_ban") / "tasks.json"

driver = get_driver()


@driver.on_startup
async def _():
    global _TASKS
    _TASKS = await read_profile()
    for task in _TASKS:
        res = task["cron"].split(" ")
        kwargs = {}
        kwargs["second"] = res[0]
        kwargs["minute"] = res[1]
        kwargs["hour"] = res[2]
        if res[3] != "?":
            kwargs["day"] = res[3]
        if res[4] != "?":
            kwargs["month"] = res[4]
        if res[5] != "?":
            kwargs["week"] = res[5]
        if len(res) > 6 and res[6] != "?" and res[6] != "":
            kwargs["year"] = res[6]
        scheduler.add_job(
            func=mute,
            trigger="cron",
            id=task["id"],
            kwargs={
                "user_id": task["user_id"],
                "group_id": task["group_id"],
                "time": task["time"],
                "once": task["once"],
                "id": task["id"],
            },
            **kwargs,
        )
        logger.info(f"添加定时任务：{task['id']}")


@cmd.assign("列表")
async def _(bot: Bot, session: Uninfo):
    group_id = session.group.id  # type: ignore
    ls = await read_profile()
    forward_contents = [Message(repr(task)) for task in ls]
    try:
        await bot.call_api("send_forward_msg", group_id=group_id, messages=forward_contents, prompt="禁言任务列表")
    except Exception as e:
        logger.error(f"发送失败：{repr(e)}")
        forward_contents = "\n".join([str(task) for task in ls])
        await bot.call_api("send_group_msg", group_id=group_id, message=forward_contents)


@cmd.assign("移除")
async def _(id: Match[str]):
    global _TASKS
    new_tasks = []
    for task in _TASKS:
        if task["id"] != id.result:
            new_tasks.append(task)
        else:
            # 移除定时任务
            scheduler.remove_job(job_id=id.result)
            await cmd.send(f"已移除定时任务：{id.result}")
    else:
        _TASKS = new_tasks
        await write_profile()


@cmd.assign("添加")
async def _(
    bot: Bot,
    user: Match[At],
    time: Match[int],
    session: Uninfo,
    once: Query[bool] = Query("once.val"),
    cron: Query[str] = Query("cron.val"),
    second: Query[str] = Query("second.val"),
    minute: Query[str] = Query("minute.val"),
    hour: Query[str] = Query("hour.val"),
    day: Query[str] = Query("day.val"),
    month: Query[str] = Query("month.val"),
    week: Query[str] = Query("week.val"),
    year: Query[str] = Query("year.val"),
):
    group_id = session.group.id  # type: ignore
    once_seg = once.result if once.available else True
    if (
        not cron.available
        and not second.available
        and not minute.available
        and not hour.available
        and not day.available
        and not month.available
        and not week.available
        and not year.available
    ):
        # 即刻禁言
        await bot.call_api("set_group_ban", user_id=user.result.target, group_id=group_id, duration=time.result)
        await cmd.finish()
    # 按参数禁言
    if cron.available:
        res = cron.result.split(" ")
        kwargs = {}
        kwargs["second"] = res[0]
        kwargs["minute"] = res[1]
        kwargs["hour"] = res[2]
        if res[3] != "?":
            kwargs["day"] = res[3]
        if res[4] != "?":
            kwargs["month"] = res[4]
        if res[5] != "?":
            kwargs["week"] = res[5]
        if len(res) > 6 and res[6] != "?":
            kwargs["year"] = res[6]
        await add_schedule_ban(
            user_id=user.result.target,
            group_id=group_id,
            time=time.result,
            once=once_seg,
            **kwargs,
        )
    else:
        kwargs = {}
        if second.available:
            kwargs["second"] = second.result
        if minute.available:
            kwargs["minute"] = minute.result
        if hour.available:
            kwargs["hour"] = hour.result
        if day.available:
            kwargs["day"] = day.result
        if month.available:
            kwargs["month"] = month.result
        if week.available:
            kwargs["week"] = week.result
        if year.available:
            kwargs["year"] = year.result
        await add_schedule_ban(
            user_id=user.result.target,
            group_id=group_id,
            time=time.result,
            once=once_seg,
            **kwargs,
        )


async def add_schedule_ban(
    user_id: str,
    group_id: str,
    time: int,
    once: bool,
    **kwargs,
):
    global _TASKS
    id = generate_random_string(8)
    # 写入配置文件
    task = BanTask(
        id=id,
        user_id=user_id,
        group_id=group_id,
        time=time,
        once=once,
        cron=f"{kwargs.get('second', '0')} {kwargs.get('minute', '0')} {kwargs.get('hour', '0')} {kwargs.get('day', '?')} {kwargs.get('month', '?')} {kwargs.get('week', '?')}",
    )
    _TASKS.append(task)
    await write_profile()
    await cmd.send(f"已添加定时任务：{id}")

    scheduler.add_job(
        func=mute,
        trigger="cron",
        id=id,
        kwargs={
            "user_id": user_id,
            "group_id": group_id,
            "time": time,
            "once": once,
            "id": id,
        },
        **kwargs,
    )


async def mute(user_id: str, group_id: str, time: int, once: bool, id: str):
    global _TASKS
    bot = get_bot()
    await bot.call_api("set_group_ban", user_id=user_id, group_id=group_id, duration=time)
    if once:
        # 移除定时任务，删除配置文件
        _TASKS = [task for task in _TASKS if task["id"] != id]
        scheduler.remove_job(job_id=id)
        await write_profile()


async def write_profile():
    """写入配置"""
    global _SCHEDULE_BAN_PROFILE
    global _TASKS
    _SCHEDULE_BAN_PROFILE.write_text(json.dumps(_TASKS))


async def read_profile() -> list[BanTask]:
    """读取配置"""
    global _SCHEDULE_BAN_PROFILE
    global _TASKS
    if not _SCHEDULE_BAN_PROFILE.exists():
        _SCHEDULE_BAN_PROFILE.touch()
        return []
    else:
        text = _SCHEDULE_BAN_PROFILE.read_text()
        if not text:
            return []
        _TASKS = json.loads(text)
        return _TASKS
