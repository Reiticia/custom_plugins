from pathlib import Path
from nonebot import logger
import nonebot_plugin_localstore as store

from playwright.async_api import async_playwright
from datetime import datetime


class Browser:
    def __init__(self):
        self.browser = None

    async def setup(self):
        if not self.browser:
            p = await async_playwright().start()
            self.browser = await p.firefox.launch()  # 启动浏览器

    async def close(self):
        if self.browser:
            await self.browser.close()  # 关闭浏览器

    async def capture_screenshot(
        self, url: str, *, start_x=0, start_y=0, width=1920, height=1080, scroll_x=0, scroll_y=0, full_page=False
    ) -> Path:
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
        # 启动 Chromium 浏览器（可以选择 'chromium'、'firefox' 或 'webkit'）
        browser = self.browser
        # 创建一个新的页面
        page = await browser.new_page()
        # 导航到目标网址
        await page.goto(url)
        await page.evaluate(
            "(x, y) => window.scrollTo(x, y);", [scroll_x, scroll_y]
        )  # 滚动页面，使元素可见（如果有需要）
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(100)
        # 截取整个页面的截图并保存为 img_store
        if full_page:
            await page.screenshot(path=img_store, full_page=True)
        else:
            await page.screenshot(path=img_store, clip={"x": start_x, "y": start_y, "width": width, "height": height})
        return img_store
