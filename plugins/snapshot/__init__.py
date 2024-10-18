from pathlib import Path
from typing import Optional
from nonebot.rule import to_me
from nonebot import get_plugin_config, logger, require, get_driver
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, AlconnaMatches, Args, Arparma, Image, Match, Option, UniMessage, on_alconna
from .browser import Browser

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="snapshot",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

require("nonebot_plugin_localstore")
require("nonebot_plugin_alconna")

firefox = Browser()

dirver = get_driver()


@dirver.on_bot_connect
async def _():
    await firefox.setup()


# @dirver.on_shutdown
# async def _():
#     await firefox.close()


snapshot = on_alconna(
    Alconna(
        "snapshot",
        Args["url", str],
        Option("-f|--full-page", Args["full_page", Optional[bool]]),
        Option("-x|--start-x", Args["x", float]),
        Option("-y|--start-y", Args["y", float]),
        Option("-sx|--scroll-x", Args["scroll_x", float]),
        Option("-sy|--scroll-y", Args["scroll_y", float]),
        Option("-w|--width", Args["width", float]),
        Option("-H|--height", Args["height", float]),
    ),
    aliases={"render", "截图"},
    rule=to_me,
)


@snapshot.handle()
async def _(url: Match[str], args: Arparma = AlconnaMatches()):
    if args.options.get("full-page").value is None:
        logger.debug("开始截图全屏")
        path = await firefox.capture_screenshot(url.result, full_page=True)
        logger.debug(f"截图成功：{path}")
    else:
        start_x = args.query[float]("x") if args.find("x") else 0
        start_y = args.query[float]("y") if args.find("y") else 0
        width = args.query[float]("width") if args.find("width") else 1920
        height = args.query[float]("height") if args.find("height") else 1080
        scroll_x = args.query[float]("scroll_x") if args.find("scroll_x") else 0
        scroll_y = args.query[float]("scroll_y") if args.find("scroll_y") else 0
        logger.debug(f"开始截图：{url.result}，坐标：({start_x}, {start_y})，大小：({width}, {height})，滚动：({scroll_x}, {scroll_y})")
        path = await firefox.capture_screenshot(
            url.result,
            start_x=start_x,
            start_y=start_y,
            width=width,
            height=height,
            scroll_x=scroll_x,
            scroll_y=scroll_y,
        )
        logger.debug(f"截图成功：{path}")
    bytes = get_image_bytes(path)
    clear_cache(path)
    await snapshot.send(await UniMessage(Image(raw=bytes)).export())


def clear_cache(path: Path):
    """清除缓存

    Args:
        path (str): 图片路径
    """
    if path.exists():
        path.unlink()
        logger.debug(f"缓存已清除：{path}")


def get_image_bytes(image_path: Path):
    # 打开图片文件并读取其二进制内容
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    return image_bytes
