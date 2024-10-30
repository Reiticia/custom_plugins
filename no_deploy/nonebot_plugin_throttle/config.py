from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    throttle_time_out: int = 10  # seconds


plugin_config = get_plugin_config(Config)
