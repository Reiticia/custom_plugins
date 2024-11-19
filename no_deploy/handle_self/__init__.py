from nonebot import logger, on_command
from nonebot.plugin import PluginMetadata
from nonebot.message import event_preprocessor, handle_event
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent, GroupMessageEvent, Bot, PrivateMessageEvent, Message
from asyncio import create_task, sleep
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11.bot import _check_reply, _check_at_me, _check_nickname

from .config import Config, plugin_config

__plugin_meta__ = PluginMetadata(
    name="handle_self",
    description="",
    usage="",
    config=Config,
)


@event_preprocessor
async def global_self_message(bot: Bot, event: Event):
    logger.debug(event.get_type())
    # 如果是自身消息且全局开关开启
    if event.get_type() == "message_sent" and plugin_config.enable_handle_self:
        await sleep(delay=plugin_config.replay_time)
        d = event.model_dump()
        del d["post_type"]
        if d["message_type"] == "group":
            e = GroupMessageEvent(
                **d, post_type="message", original_message=d["message"], anonymous=None, to_me=False, reply=None
            )
            _check_nickname(bot=bot, event=e)
            await _check_reply(bot=bot, event=e)
            _check_at_me(bot=bot, event=e)
            create_task(handle_event(bot, e))
        if d["message_type"] == "private":
            e = PrivateMessageEvent(
                **d,
                post_type="message",
                original_message=d["message"],
                to_me=plugin_config.self_report_tome,
                reply=None,
            )
            await _check_reply(bot=bot, event=e)
            create_task(handle_event(bot, e))


def _check_super_user_or_self(bot: Bot, event: MessageEvent):
    return event.get_user_id() in bot.config.superusers or event.get_user_id() == str(event.self_id)

def _check_self(bot: Bot, event: Event):
    event.get_type() == "message_sent" or event.get_user_id() == bot.self_id


@on_command(cmd="echo", rule=Rule(_check_super_user_or_self)).handle()
async def handle_self(event: MessageEvent, matcher: Matcher, args: Message = CommandArg()):
    logger.debug(event.model_dump())
    logger.debug("处理消息")
    if event.get_user_id() == event.self_id:
        logger.debug("处理自身消息")
    await matcher.send(args)
