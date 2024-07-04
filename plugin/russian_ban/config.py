from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    increase_probability: bool = False
    """增加被禁言的概率"""
    increase_duration: bool = True
    """增加被禁言的时长"""
