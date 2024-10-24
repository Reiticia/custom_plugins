from nonebot.plugin import PluginMetadata
from nonebot import require

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-shellcrash",
    description="",
    usage="",
    config=Config,
)

require("nonebot_plugin_alconna")
require("nonebot_plugin_waiter")
require("nonebot_plugin_htmlrender")

from . import command