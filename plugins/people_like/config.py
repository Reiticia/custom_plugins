from typing import Optional
from pydantic import BaseModel
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    black_list: list[int] = []
    """黑名单，不做检测"""
    reply_probability: float = 0.05
    """回复概率"""
    repeat_probability: float = 0.01
    """复读概率"""
    context_size: int = 20
    """上下文长度"""
    one_word_max_used_time_of_second: int = 1
    """一个字最多花费多少时间"""
    image_analyze: bool = True
    """是否开启图片分析"""
    gemini_key: Optional[str]
    """Gemini API Key"""


plugin_config = get_plugin_config(Config)
