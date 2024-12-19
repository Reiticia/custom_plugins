import json
from nonebot import on_command, require, get_driver
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.permission import SUPERUSER
from nonebot.matcher import Matcher
from nonebot.rule import to_me
from aiofiles import open
from typing import Optional
from nonebot.adapters.onebot.v11 import Bot

driver = get_driver()


require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402

_CONFIG_DIR = store.get_config_dir("people_like")

PROMPT: str = ""


def get_prompt() -> Optional[str]:
    global PROMPT
    return None if not PROMPT else PROMPT


@on_command(cmd="promptset", permission=SUPERUSER, rule=to_me()).handle()
async def _(args: Message = CommandArg()):
    global PROMPT
    PROMPT = args.extract_plain_text()


@on_command(cmd="promptget", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global PROMPT
    await matcher.send("nothing" if not PROMPT else PROMPT)


TOP_P: Optional[float] = None


def get_top_p() -> Optional[float]:
    global TOP_P
    return TOP_P


@on_command(cmd="pset", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher, args: Message = CommandArg()):
    global TOP_P
    TOP_P = float(args.extract_plain_text())
    await matcher.send(str(TOP_P))


@on_command(cmd="pget", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global TOP_P
    await matcher.send(str(TOP_P))


TOP_K: Optional[int] = None


def get_top_k() -> Optional[int]:
    global TOP_K
    return TOP_K


@on_command(cmd="kset", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher, args: Message = CommandArg()):
    global TOP_K
    TOP_K = int(args.extract_plain_text())
    await matcher.send(str(TOP_K))


@on_command(cmd="kget", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global TOP_K
    await matcher.send(str(TOP_K))


@on_command(cmd="write", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global TOP_P, TOP_K, PROMPT, _CONFIG_DIR
    content = {
        "TOP_P": TOP_P,
        "TOP_K": TOP_K,
        "PROMPT": PROMPT,
    }
    f = _CONFIG_DIR / "people_like.json"
    async with open(f, "w", encoding="utf-8") as f:
        await f.write(json.dumps(content))
    await matcher.send("配置文件 people_like.json 已保存")


@driver.on_bot_connect
async def _(bot: Bot):
    global TOP_P, TOP_K, PROMPT, _CONFIG_DIR
    f = _CONFIG_DIR / "people_like.json"
    try:
        async with open(f, "r", encoding="utf-8") as f:
            content = json.loads(await f.read())
            TOP_P = content["TOP_P"]
            TOP_K = content["TOP_K"]
            PROMPT = content["PROMPT"]
    except FileNotFoundError:
        for user in [user for user in bot.config.superusers if user != bot.self_id]:
            await bot.send_private_msg(user_id=int(user), message="配置文件 people_like.json 不存在")
    else:
        for user in [user for user in bot.config.superusers if user != bot.self_id]:
            await bot.send_private_msg(user_id=int(user), message="配置文件 people_like.json 已读取")
