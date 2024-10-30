from nonebot_plugin_uninfo.permission import ADMIN, OWNER, MEMBER
from nonebot.permission import SUPERUSER

admin_permission = SUPERUSER | ADMIN | OWNER
"""管理权限
"""
