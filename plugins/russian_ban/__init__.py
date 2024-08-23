from .metadata import __plugin_meta__ as __plugin_meta__
from nonebot import require

require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_orm")
require("nonebot_plugin_waiter")

from . import command
