import re

from typing import Optional
from nonebot import logger, require, get_driver
from nonebot.message import run_postprocessor
from nonebot.matcher import Matcher
from nonebot.exception import FinishedException
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
    Text,
    UniMessage,
    MultiVar,
    AlconnaMatches,
    on_alconna,
)
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyMergeExtension
from .browser import Browser

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="snapshot",
    description="",
    usage="",
    config=Config,
)


require("nonebot_plugin_alconna")

firefox = Browser()

dirver = get_driver()


@dirver.on_bot_connect
async def _():
    await firefox.setup()


args_key = "url"
args_key_type = Text | At | Image

snapshot = on_alconna(
    Alconna(
        "snapshot",
        Args[args_key, MultiVar(args_key_type, "*")],
        Option("-f|--full-page", Args["full_page", Optional[bool]]),
        Option("-x|--start-x", Args["x", float]),
        Option("-y|--start-y", Args["y", float]),
        Option("-sx|--scroll-x", Args["scroll_x", float]),
        Option("-sy|--scroll-y", Args["scroll_y", float]),
        Option("-w|--width", Args["width", float]),
        Option("-H|--height", Args["height", float]),
    ),
    aliases={"render", "截图"},
    response_self=True,
    extensions=[ReplyMergeExtension()],
)


@snapshot.handle()
async def _(alc_matches: AlcMatches, args: Arparma = AlconnaMatches()):
    is_full_page = args.options.get("full-page").value is None
    start_x = args.query[float]("x") if args.find("x") else 0
    start_y = args.query[float]("y") if args.find("y") else 0
    width = args.query[float]("width") if args.find("width") else 1920
    height = args.query[float]("height") if args.find("height") else 1080
    scroll_x = args.query[float]("scroll_x") if args.find("scroll_x") else 0
    scroll_y = args.query[float]("scroll_y") if args.find("scroll_y") else 0
    args: list[args_key_type] = list(alc_matches.query(args_key, ()))
    args = [arg for arg in args if isinstance(arg, Text)]
    urls = [arg.text for arg in args if is_url(arg.text)]
    if not urls:
        await snapshot.finish("请输入网址或回复一条带网址消息")
    for url in urls:
        await snapshot_handle(url, is_full_page, start_x, start_y, scroll_x, scroll_y, width, height)


async def snapshot_handle(
    url: str,
    full_page: bool = False,
    x: float = 0,
    y: float = 0,
    scroll_x: float = 0,
    scroll_y: float = 0,
    width: float = 1920,
    height: float = 1080,
):
    if full_page:
        logger.debug("开始截图全屏")
        screenshot_bytes = await firefox.capture_screenshot(url, full_page=True)
        logger.debug("截图成功")
    else:
        logger.debug(f"开始截图：{url}，坐标：({x}, {y})，大小：({width}, {height})，滚动：({scroll_x}, {scroll_y})")
        screenshot_bytes = await firefox.capture_screenshot(
            url,
            start_x=x,
            start_y=y,
            width=width,
            height=height,
            scroll_x=scroll_x,
            scroll_y=scroll_y,
        )
        logger.debug("截图成功")
    await snapshot.send(await UniMessage(Image(raw=screenshot_bytes)).export())


@run_postprocessor
async def do_something(matcher: Matcher, exception: Optional[Exception]):
    if exception and not isinstance(exception, FinishedException):
        await matcher.send(repr(exception))


def is_url(text: str) -> Match[str] | None:
    # 正则表达式匹配 URL
    url_pattern = r"(https?://[^\s]+)"
    return re.match(url_pattern, text)
