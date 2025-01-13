from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""
    banlist: list[int] = []


plugin_config = get_plugin_config(Config)