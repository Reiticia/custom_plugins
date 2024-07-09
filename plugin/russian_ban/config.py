from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    increase_probability: bool = False
    """增加被禁言的概率"""
    increase_duration: bool = True
    """增加被禁言的时长"""
    voting_member_count: int = 3
    """投票成功人数"""

config = get_plugin_config(Config)