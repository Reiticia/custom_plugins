from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="nonebot_plugin_debounce",
    description="防抖",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

