from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    throttle_time_out: int = 5
    """隔多少分钟可触发指令
    """
    throttle_count_limit: int = 1
    """在间隔时间内允许触发指令的次数，与上一个配置项结合。
    即在 throttle_time_out 秒内，允许有 throttle_count_limit 次触发指令。
    """

plugin_config = get_plugin_config(Config)
