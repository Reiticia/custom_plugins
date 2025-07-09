
from nonebot import logger, on_command
from nonebot_plugin_apscheduler import scheduler
from nonebot.rule import to_me
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from .setting import get_value_or_default

ALL_MODEL = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite-preview-06-17", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
CURRENT_MODEL_INDEX = 0
DAILY_FAIL_COUNT: list[int] = [0] * len(ALL_MODEL)


@scheduler.scheduled_job("interval", minutes=1, id="reset_model_index_minute")
def reset_model_index_minute():
    global CURRENT_MODEL_INDEX, DAILY_FAIL_COUNT
    pre_model = ALL_MODEL[CURRENT_MODEL_INDEX]
    for i in range(0, len(ALL_MODEL)):
        CURRENT_MODEL_INDEX = i
        if DAILY_FAIL_COUNT[CURRENT_MODEL_INDEX] >= 3:
            logger.info(f"模型{ALL_MODEL[CURRENT_MODEL_INDEX]}已在今日内禁用")
        else:
            if pre_model != ALL_MODEL[CURRENT_MODEL_INDEX]:
                logger.info(f"模型{pre_model}已禁用，切换到模型{ALL_MODEL[CURRENT_MODEL_INDEX]}")
            break
    else:
        DAILY_FAIL_COUNT = [0] * len(ALL_MODEL)


@scheduler.scheduled_job("interval", days=1, id="reset_model_index_day")
def reset_model_index_day():
    global CURRENT_MODEL_INDEX, DAILY_FAIL_COUNT
    CURRENT_MODEL_INDEX = 0
    DAILY_FAIL_COUNT = [0] * len(ALL_MODEL)


def change_model():
    global CURRENT_MODEL_INDEX, DAILY_FAIL_COUNT
    DAILY_FAIL_COUNT[CURRENT_MODEL_INDEX] += 1
    for i in range(CURRENT_MODEL_INDEX, len(ALL_MODEL)):
        CURRENT_MODEL_INDEX = i
        if DAILY_FAIL_COUNT[CURRENT_MODEL_INDEX] >= 3:
            logger.info(f"模型{ALL_MODEL[CURRENT_MODEL_INDEX]}已在今日内禁用")
        else:
            logger.info(f"已启用模型{ALL_MODEL[CURRENT_MODEL_INDEX]}")
            break
    else:
        DAILY_FAIL_COUNT = [0] * len(ALL_MODEL)


def get_model(group_id: int) -> str:
    default_model = ALL_MODEL[CURRENT_MODEL_INDEX]
    return get_value_or_default(group_id, "model", default_model)


@on_command("当前模型", permission=SUPERUSER, rule=to_me(), priority=1, block=True).handle()
async def current_model(bot: Bot, matcher: Matcher, e: MessageEvent):
    model = ALL_MODEL[CURRENT_MODEL_INDEX]
    logger.info(f"当前模型{model}")
    await matcher.finish(model)
