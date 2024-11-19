import re

from typing import Optional
from nonebot import logger, require, get_driver
from nonebot.plugin import PluginMetadata
from re import Match as reMatch
from nonebot_plugin_alconna import (
    AlcMatches,
    Alconna,
    Args,
    Arparma,
    At,
    Image,
    Match,
    Option,
    Subcommand,
    Text,
    UniMessage,
    MultiVar,
    AlconnaMatches,
    UniMsg,
    on_alconna,
)
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyMergeExtension
from .browser import Browser
import json

from .config import Config
from common.permission import admin_permission

__plugin_meta__ = PluginMetadata(
    name="snapshot",
    description="",
    usage="",
    config=Config,
)

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")
require("nonebot_plugin_uninfo")

import nonebot_plugin_localstore as store
from nonebot_plugin_waiter import waiter


firefox = Browser()

dirver = get_driver()


@dirver.on_bot_connect
async def _():
    await firefox.setup()


black_list: set[str] = set()

black_list_file = store.get_config_dir("snapshot") / "black_list.json"


@dirver.on_bot_connect
async def read_black_list():
    global black_list, black_list_file
    if black_list_file.exists():
        with open(black_list_file, "r", encoding="utf-8") as f:
            black_list = set(json.load(f))
    else:
        with open(black_list_file, "w", encoding="utf-8") as f:
            json.dump(list(black_list), f)


args_key = "url"
args_key_type = Text | At | Image

snapshot = on_alconna(
    Alconna(
        Args["reply_user?", At | int],
        "snapshot",
        Args[args_key, MultiVar(args_key_type, "*")],
        Option("-f|--full-page", Args["full_page", Optional[bool]]),
        Option("-s|--save", Args["save", Optional[bool]]),
        Option("-x|--start-x", Args["x", float]),
        Option("-y|--start-y", Args["y", float]),
        Option("-w|--width", Args["width", float]),
        Option("-H|--height", Args["height", float]),
    ),
    aliases={"render", "截图"},
    response_self=True,
    extensions=[ReplyMergeExtension()],
)

block = on_alconna(
    Alconna(
        "url block",
        Subcommand("add", Args["pattern", str]),
        Subcommand("remove", Args["pattern", str]),
        Subcommand("list"),
    ),
    permission=admin_permission,
    response_self=True,
)


@block.assign("add")
async def block_add(pattern: Match[str]):
    global black_list, black_list_file
    black_list.add(pattern.result)
    logger.debug(f"当前屏蔽列表：{black_list}")
    with open(black_list_file, "w", encoding="utf-8") as f:
        json.dump(list(black_list), f)
    await block.finish(f"已添加 {pattern.result} 屏蔽")


@block.assign("remove")
async def block_remove(pattern: Match[str]):
    global black_list, black_list_file
    black_list.remove(pattern.result)
    logger.debug(f"当前屏蔽列表：{black_list}")
    with open(black_list_file, "w", encoding="utf-8") as f:
        json.dump(list(black_list), f)
    await block.finish(f"已移除 {pattern.result} 屏蔽")


@block.assign("list")
async def list_block():
    global black_list
    block_list = "\n".join(black_list)
    await block.finish(f"当前屏蔽列表：\n{block_list}")


@snapshot.handle()
async def _(alc_matches: AlcMatches, args: Arparma = AlconnaMatches()):
    is_full_page = x.value is None if (x := args.options.get("full-page")) else False
    is_save = x.value is None if (x := args.options.get("save")) else False
    start_x = float(str(args.query[float]("x") if args.find("x") else 0))
    start_y = float(str(args.query[float]("y") if args.find("y") else 0))
    width = float(str(args.query[float]("width") if args.find("width") else 1920))
    height = float(str(args.query[float]("height") if args.find("height") else 1080))
    args_res: list[args_key_type] = list(alc_matches.query(args_key, ()))
    text_args = [arg.text for arg in args_res if isinstance(arg, Text)]
    url_args: list[str] = []
    for arg in text_args:
        arg_arr = arg.split(" ")
        url_args.extend(arg_arr)
    urls = [arg for arg in url_args if is_url(arg)]
    if not urls:
        await snapshot.finish("请输入网址或回复一条带网址消息")
    for url in urls:
        if is_blocked_url(url):
            await snapshot.send(f"网址 {url} 已被屏蔽")
            return
        await snapshot_handle(url, is_full_page, start_x, start_y, width, height, is_save)


async def snapshot_handle(
    url: str,
    full_page: bool = False,
    x: float = 0,
    y: float = 0,
    width: float = 1920,
    height: float = 1080,
    save: bool = False,
):
    if full_page:
        logger.debug("开始截图全屏")
        res = await firefox.capture_screenshot(url, full_page=True)
        if isinstance(e := res, Exception):
            await UniMessage.text(text=repr(e)).finish()
        logger.debug("截图成功")
    else:
        logger.debug(f"开始截图：{url}，坐标：({x}, {y})，大小：({width}, {height})")
        try:
            res = await firefox.capture_screenshot(
                url,
                start_x=int(x),
                start_y=int(y),
                width=int(width),
                height=int(height),
            )
        except Exception as e:
            await UniMessage.text(text=repr(e)).finish()
        logger.debug("截图成功")
    r = await UniMessage.image(raw=res).send()

    if save:
        await UniMessage().finish()

    @waiter(["message"], keep_session=True)
    async def receive(msg: UniMsg):
        return str(msg) == "save"

    await UniMessage.text(text="如需保存图片请输入save").send()

    # 是否撤回，默认撤回
    async for res in receive(timeout=10, retry=3, prompt=""):
        # 如果超时未输入
        if res is None:
            if r.recallable:
                await UniMessage.text(text="超时未输入，撤回图片").send()
                await r.recall(delay=0, index=0)
            break
        if res is False:
            continue
        await UniMessage.text(text="图片已保存").send()
        break
    else:
        if r.recallable:
            await UniMessage.text(text="已超出保存图片的消息次数，撤回图片").send()
            await r.recall(delay=0, index=0)


def is_url(text: str) -> reMatch[str] | None:
    # 正则表达式匹配 URL
    url_pattern = r"(https?://[^\s]+)"
    return re.match(url_pattern, text)


def is_blocked_url(url: str) -> bool:
    global black_list
    for block_url in black_list:
        try:
            if re.match(block_url, url):
                return True
        except re.error:
            pass
    return False
