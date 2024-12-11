import json
from nonebot import on_command, require
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.permission import SUPERUSER
from nonebot.matcher import Matcher
from nonebot.rule import to_me
from aiofiles import open


require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store  # noqa: E402

_CONFIG_DIR = store.get_config_dir("people_like")

PROMPT: str = ""


@on_command(cmd="promptset", permission=SUPERUSER, rule=to_me()).handle()
async def _(args: Message = CommandArg()):
    global PROMPT
    PROMPT = args.extract_plain_text()


@on_command(cmd="promptget", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global PROMPT
    await matcher.send(PROMPT)


TOP_P: float = 0.0


@on_command(cmd="pset", permission=SUPERUSER, rule=to_me()).handle()
async def _(args: Message = CommandArg()):
    global TOP_P
    TOP_P = float(args.extract_plain_text())


@on_command(cmd="pget", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global TOP_P
    await matcher.send(str(TOP_P))


TOP_K: float = 0.0


@on_command(cmd="kset", permission=SUPERUSER, rule=to_me()).handle()
async def _(args: Message = CommandArg()):
    global TOP_K
    TOP_K = float(args.extract_plain_text())


@on_command(cmd="kget", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher):
    global TOP_K
    await matcher.send(str(TOP_K))


@on_command(cmd="profilewrite", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher, args: Message = CommandArg()):
    global TOP_P, TOP_K, PROMPT, _CONFIG_DIR
    content = {
        "TOP_P": TOP_P,
        "TOP_K": TOP_K,
        "PROMPT": PROMPT,
    }
    f = _CONFIG_DIR / f"{args.extract_plain_text()}.json"
    async with open(f, "w", encoding="utf-8") as f:
        await f.write(json.dumps(content))
    await matcher.send(f"配置文件 {f} 已保存")


@on_command(cmd="profileread", permission=SUPERUSER, rule=to_me()).handle()
async def _(matcher: Matcher, args: Message = CommandArg()):
    global TOP_P, TOP_K, PROMPT, _CONFIG_DIR
    content = {
        "TOP_P": TOP_P,
        "TOP_K": TOP_K,
        "PROMPT": PROMPT,
    }
    f = _CONFIG_DIR / f"{args.extract_plain_text()}.json"
    async with open(f, "r", encoding="utf-8") as f:
        content = json.loads(await f.read())
    TOP_P = content["TOP_P"]
    TOP_K = content["TOP_K"]
    PROMPT = content["PROMPT"]
    await matcher.send(f"配置文件 {f} 已读取")
