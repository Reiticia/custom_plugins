import re

from typing import Optional
from nonebot import logger, require, get_driver
from nonebot.plugin import PluginMetadata
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
from ..common.permission import admin_permission

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
    is_full_page = args.options.get("full-page").value is None
    is_save = args.options.get("save").value is None
    start_x = args.query[float]("x") if args.find("x") else 0
    start_y = args.query[float]("y") if args.find("y") else 0
    width = args.query[float]("width") if args.find("width") else 1920
    height = args.query[float]("height") if args.find("height") else 1080
    args: list[args_key_type] = list(alc_matches.query(args_key, ()))
    args = [arg for arg in args if isinstance(arg, Text)]
    urls = [arg.text for arg in args if is_url(arg.text)]
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
        res = await firefox.capture_screenshot(
            url,
            start_x=x,
            start_y=y,
            width=width,
            height=height,
        )
        if isinstance(e := res, Exception):
            await UniMessage.text(text=repr(e)).finish()
        logger.debug("截图成功")
    r = await UniMessage.image(raw=res).send()

    if save:
        await UniMessage.finish()

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


def is_url(text: str) -> Match[str] | None:
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
