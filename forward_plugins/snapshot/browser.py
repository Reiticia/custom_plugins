from nonebot import logger

from playwright.async_api import async_playwright
from playwright.async_api._generated import Page


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
    ) -> bytes:
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
        # 启动 Chromium 浏览器（可以选择 'chromium'、'firefox' 或 'webkit'）
        browser = self.browser
        if not browser:
            raise Exception("浏览器未启动")
        # 创建一个新的页面
        page: Page = await browser.new_page()
        # 导航到目标网址
        _resp = await page.goto(url, wait_until="networkidle")
        # 截取整个页面的截图并保存为 img_store
        if full_page:
            # 解决网页图片懒加载问题
            await self.__auto_scroll(page)  # 使用滚轮
            # page.wait_for_load_state()
            screenshot_bytes = await page.screenshot(full_page=True)
        else:
            screenshot_bytes = await page.screenshot(
                clip={"x": start_x, "y": start_y, "width": width, "height": height}
            )
        # 关闭页面
        await page.close()
        return screenshot_bytes

    async def __auto_scroll(self, page: Page):
        await page.evaluate("""async () => {
            await new Promise((resolve, reject) => {
                var totalHeight = 0;
                var distance = 100;
                var timer = setInterval(() => {
                    var scrollHeight = document.body.scrollHeight;
                    window.scrollBy(0, distance);
                    totalHeight += distance;

                    if(totalHeight >= scrollHeight){
                        clearInterval(timer);
                        window.scrollTo(0, 0);
                        resolve();
                    }
                }, 100);
            });
        }""")
