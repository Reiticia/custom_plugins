from nonebot import require
import random
import string

require("nonebot_plugin_uninfo")



def generate_random_string(length: int) -> str:
    """生成指定长度的随机字符串

    Args:
        length (int): 长度

    Returns:
        str: 结果
    """
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

