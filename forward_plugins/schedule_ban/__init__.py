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
        "mute",
        Subcommand(
            "add",
            Args["user", At, "要禁言的用户"],
            Args["time", int, "禁言时长（秒）"],
            Option("-o|--once", Args["val", bool], help_text="是否一次性任务"),
            Option("-c|--cron", Args["val", str], help_text="cron表达式"),
            Option("-s|--second", Args["val", str], help_text="秒"),
            Option("-m|--minute", Args["val", str], help_text="分"),
            Option("-H|--hour", Args["val", str], help_text="时"),
            Option("-d|--day", Args["val", str], help_text="日"),
            Option("-M|--month", Args["val", str], help_text="月"),
            Option("-w|--week", Args["val", str], help_text="周"),
            Option("-y|--year", Args["val", str], help_text="年"),
            help_text="添加定时禁言任务",
            alias={"添加", "设置"},
        ),
        Subcommand("list", help_text="查看所有定时禁言任务", alias={"列表"}),
        Subcommand(
            "remove",
            Args["id", str, "要移除的任务ID"],
            help_text="移除定时禁言任务",
            alias={"移除", "删除"},
        ),
    ),
    aliases={"禁言"},
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
        kwargs = {
            "second": res[0],
            "minute": res[1],
            "hour": res[2],
            "day": res[3] if res[3] != "?" else None,
            "month": res[4] if res[4] != "?" else None,
            "week": res[5] if res[5] != "?" else None,
            "year": res[6] if len(res) > 6 and res[6] != "?" and res[6] != "" else None,
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
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


@cmd.assign("list")
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


@cmd.assign("remove")
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


@cmd.assign("add")
async def _(
    bot: Bot,
    user: Match[At],
    time: Match[int],
    session: Uninfo,
    once: Query[bool] = Query("add.once.val"),
    cron: Query[str] = Query("add.cron.val"),
    second: Query[str] = Query("add.second.val"),
    minute: Query[str] = Query("add.minute.val"),
    hour: Query[str] = Query("add.hour.val"),
    day: Query[str] = Query("add.day.val"),
    month: Query[str] = Query("add.month.val"),
    week: Query[str] = Query("add.week.val"),
    year: Query[str] = Query("add.year.val"),
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
        kwargs = {
            "second": res[0],
            "minute": res[1],
            "hour": res[2],
            "day": res[3] if res[3] != "?" else None,
            "month": res[4] if res[4] != "?" else None,
            "week": res[5] if res[5] != "?" else None,
            "year": res[6] if len(res) > 6 and res[6] != "?" and res[6] != "" else None,
        }
        await add_schedule_ban(
            user_id=user.result.target,
            group_id=group_id,
            time=time.result,
            once=once_seg,
            **kwargs,
        )
    else:
        kwargs = {
            "second": second.result if second.available else None,
            "minute": minute.result if minute.available else None,
            "hour": hour.result if hour.available else None,
            "day": day.result if day.available else None,
            "month": month.result if month.available else None,
            "week": week.result if week.available else None,
            "year": year.result if year.available else None,
        }
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
    second_seg = 0 if (s_s := kwargs.get("second")) is None else s_s
    minute_seg = 0 if (m_s := kwargs.get("minute")) is None else m_s
    hour_seg = 0 if (h_s := kwargs.get("hour")) is None else h_s
    day_seg = "?" if (d_s := kwargs.get("day")) is None else d_s
    month_seg = "?" if (M_s := kwargs.get("month")) is None else M_s
    week_seg = "?" if (w_s := kwargs.get("week")) is None else w_s
    year_seg = "" if (y_s := kwargs.get("year")) is None else y_s
    # 写入配置文件
    task = BanTask(
        id=id,
        user_id=user_id,
        group_id=group_id,
        time=time,
        once=once,
        cron=f"{second_seg} {minute_seg} {hour_seg} {day_seg} {month_seg} {week_seg} {year_seg}",
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
