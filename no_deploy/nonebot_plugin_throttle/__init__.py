import json
import time
from nonebot import require, get_bot, logger

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")

from nonebot_plugin_alconna import Alconna, At, Match, Subcommand, Args, on_alconna
import nonebot_plugin_localstore as store
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event
from nonebot.exception import IgnoredException
from nonebot.permission import SUPERUSER

from nonebot.message import run_preprocessor
from common.struct import ExpirableDict

from .config import Config, plugin_config

__plugin_meta__ = PluginMetadata(
    name="nonebot_plugin_throttle",
    description="节流",
    usage="",
    config=Config,
)

throttle_dict: dict[str, ExpirableDict[str, str]] = {}


@run_preprocessor
async def _(event: Event, matcher: Matcher):
    """节流规则一：不同对话间互不影响，不同用户间互不影响，针对单一用户的指令进行节流。

    Args:
        event (Event): _description_

    Raises:
        IgnoredException: _description_
    """
    global throttle_dict
    session_id = (sid := event.get_session_id())[: sid.rfind("_")]
    user_id = event.get_user_id()
    if event.get_type() != "message":
        return
    # 判断白名单
    if user_id in white_list or user_id in get_bot().config.superusers or get_bot().self_id == user_id:
        logger.debug(f"用户{user_id}在白名单中，不进行节流处理")
        return
    if plugin_config.throttle_count_limit <= 0:  # 如果不配置响应次数，则对每一个用户独立进行节流
        expirable_dict = throttle_dict.get(session_id, ExpirableDict(name=session_id))
        # ttl > 0 则说明在一段时间内处理过该用户的消息，则不再处理
        if (ttl := expirable_dict.ttl(user_id)) > 0:
            tip = f"用户{user_id}在{plugin_config.throttle_time_out - ttl}秒内已处理过消息，不再处理"
            logger.warning(tip)
            await matcher.send(tip)
            raise IgnoredException("节流处理")
        else:
            expirable_dict.set(user_id, user_id, plugin_config.throttle_time_out)
            throttle_dict.update({session_id: expirable_dict})
    else:  # 如果配置了响应次数，则对同一个对话中的所有用户进行节流
        expirable_dict = throttle_dict.get(session_id, ExpirableDict(name=session_id))
        if len(keys := expirable_dict.keys()) >= plugin_config.throttle_count_limit:
            tip = "\n".join(
                [
                    f"会话{session_id}在{plugin_config.throttle_time_out}秒内已处理过{len(expirable_dict.keys())}条消息，不再处理。",
                    f"至少再过{min( expirable_dict.ttl(k) for k in keys )}秒可在进行消息处理",
                ]
            )
            logger.warning(tip)
            await matcher.send(tip)
            raise IgnoredException("节流处理")
        else:
            expirable_dict.set(str(time.time() * 1000), user_id, plugin_config.throttle_time_out)
            throttle_dict.update({session_id: expirable_dict})


white_list_setting = on_alconna(
    Alconna(
        "wl",
        Subcommand("add", Args["id", str | At]),
        Subcommand("remove", Args["id", str | At]),
        Subcommand("list"),
    ),
    permission=SUPERUSER,
)

white_list_file = store.get_config_dir("nonebot_plugin_throttle") / "white_list.json"
white_list: list[str] = json.loads(
    "[]" if not white_list_file.exists() else text if (text := white_list_file.read_text()) is not None else "[]"
)


@white_list_setting.assign("add")
async def _(id: Match[str | At], matcher: Matcher):
    global white_list
    res = r.target if isinstance(r := id.result, At) else r
    white_list.append(str(res))
    white_list_file.write_text(json.dumps(white_list))
    await matcher.finish(f"添加{res}到白名单成功")


@white_list_setting.assign("remove")
async def _(id: Match[str | At], matcher: Matcher):
    global white_list
    res = r.target if isinstance(r := id.result, At) else r
    white_list.remove(str(res))
    white_list_file.write_text(json.dumps(white_list))
    await matcher.finish(f"从白名单移除{res}成功")


@white_list_setting.assign("list")
async def _(matcher: Matcher):
    global white_list
    ls_str = "\n".join(white_list)
    await matcher.finish(f"白名单：\n{ls_str}")
