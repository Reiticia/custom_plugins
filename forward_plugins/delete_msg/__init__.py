from nonebot import get_plugin_config, on_fullmatch
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="delete_msg",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

delete_msg = on_fullmatch(msg=("删一下，谢谢", "delete, plz"))


@delete_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    reply = event.reply
    if not reply:
        await delete_msg.finish("你好歹告诉我删啥吧")
    # 发送方权限认证
    if (
        str(event.user_id) not in bot.config.superusers  # 如果不是超级用户
        and event.user_id != reply.sender.user_id
        and (
            event.sender.role == "member"  # 普通成员意图撤回其他人的消息
            or (
                event.sender.role == "admin" and reply.sender.role in ["admin", "owner"]
            )  # 管理员意图撤回其他管理员的消息
        )
    ):
        await delete_msg.finish("你的权限不足以删除该消息")
    bot_info = await bot.get_group_member_info(group_id=event.group_id, user_id=event.self_id)
    # 机器人权限认证
    if bot_info["role"] == "member" or (
        bot_info["role"] == "admin"
        and reply.sender.role in ["owner", "admin"]
        and str(reply.sender.user_id) != bot.self_id
    ):
        await delete_msg.finish("我是废物，你找别人帮你撤回吧")
    await bot.delete_msg(message_id=reply.message_id)
    await bot.delete_msg(message_id=event.message_id)
