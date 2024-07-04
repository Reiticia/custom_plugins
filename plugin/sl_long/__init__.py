from nonebot import get_plugin_config, on_regex
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="sl_long",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

@on_regex(pattern="").handle()
async def save_long():
    ...


async def load_long():
    ...