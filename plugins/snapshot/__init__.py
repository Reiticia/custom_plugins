import os
from pathlib import Path
from nonebot.rule import to_me
from nonebot import get_plugin_config, logger, require
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, AlconnaMatches, Args, Arparma, Match, Option, on_alconna
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.permission import SUPERUSER

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


snapshot = on_alconna(
    Alconna(
        "snapshot",
        Args["url", str],
        Option("-x|--start-x", Args["x", float]),
        Option("-y|--start-y", Args["y", float]),
        Option("-w|--width", Args["w", float]),
        Option("-a|--altitude", Args["a", float]),
    ),
    aliases={"render", "截图"},
    rule=to_me,
)


@snapshot.handle()
async def _(url: Match[str], args: Arparma = AlconnaMatches()):
    start_x = args.query[float]("x") if args.find("x") else 0
    start_y = args.query[float]("y") if args.find("y") else 0
    width = args.query[float]("w") if args.find("w") else 1920
    height = args.query[float]("a") if args.find("a") else 1080
    logger.debug(f"开始截图：{url.result}，坐标：({start_x}, {start_y})，大小：({width}, {height})")
    path = await capture_screenshot(url.result, start_x, start_y, width, height)
    logger.debug(f"截图成功：{path}")
    bytes = get_image_bytes(path)
    clear_cache(path)
    await snapshot.finish(Message(MessageSegment.image(bytes)))


import nonebot_plugin_localstore as store

from playwright.async_api import async_playwright
from datetime import datetime


async def capture_screenshot(url: str, start_x=0, start_y=0, width=1920, height=1080) -> Path:
    """网页截图

    Args:
        url (str): 网页URL
        start_x (int, optional): X坐标. Defaults to 0.
        start_y (int, optional): Y坐标. Defaults to 0.
        width (int, optional): 宽度. Defaults to 1920.
        height (int, optional): 高度. Defaults to 1080.

    Returns:
        str: 截图后图片路径
    """
    logger.debug(f"开始截图：{url}")
    # 获取当前时间戳（秒级别）
    timestamp = datetime.now().timestamp()
    img_store: Path = store.get_cache_dir("snapshot") / f"{timestamp}.png"
    logger.debug(f"图片保存路径：{img_store}")
    async with async_playwright() as p:
        # 启动 Chromium 浏览器（可以选择 'chromium'、'firefox' 或 'webkit'）
        browser = await p.chromium.launch()
        # 创建一个新的页面
        page = await browser.new_page()
        # 导航到目标网址
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        # 截取整个页面的截图并保存为 img_store
        await page.screenshot(path=img_store, clip={"x": start_x, "y": start_y, "width": width, "height": height})
        # 关闭浏览器
        await browser.close()

    return img_store


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
