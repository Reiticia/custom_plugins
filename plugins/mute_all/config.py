from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    all: bool = False
    """是否允许所有人使用命令"""


plugin_config = get_plugin_config(Config)
