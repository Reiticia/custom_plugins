from nonebot import logger

from playwright.async_api import async_playwright


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
        self, url: str, *, start_x=0, start_y=0, width=1920, height=1080, full_page=False
    ) -> bytes | Exception:
        """网页截图

        Args:
            url (str): 网页URL
            start_x (int, optional): X坐标. Defaults to 0.
            start_y (int, optional): Y坐标. Defaults to 0.
            width (int, optional): 宽度. Defaults to 1920.
            height (int, optional): 高度. Defaults to 1080.

        Returns:
            bytes: 截图后图片二进制数据
        """
        logger.debug(f"开始截图：{url}")
        try:
            # 启动 Chromium 浏览器（可以选择 'chromium'、'firefox' 或 'webkit'）
            browser = self.browser
            # 创建一个新的页面
            page = await browser.new_page()
            # 导航到目标网址
            _resp = await page.goto(url, wait_until="networkidle")
            # 截取整个页面的截图并保存为 img_store
            if full_page:
                screenshot_bytes = await page.screenshot(full_page=True)
            else:
                screenshot_bytes = await page.screenshot(
                    clip={"x": start_x, "y": start_y, "width": width, "height": height}
                )
            # 关闭页面
            await page.close()
            return screenshot_bytes
        except Exception as e:
            return e
