from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    increase_probability: bool = False
    """增加被禁言的概率"""
    increase_duration: bool = True
    """增加被禁言的时长"""
    msg_count_max_last_vote: int = 20
    """投票最大消息间隙"""

config = get_plugin_config(Config)