1. 普通文本消息回应
2. 图片表情消息回应
3. face表情消息回应
4. 在消息中提及群员
5. 根据回复时间延迟判断是否需要reply原消息（改进: 判断与原来消息的相关性，如果相关则 reply，否则不 reply）
6. 作为管理员时具有禁言指定群员功能
7. 根据用户对话内容分析用户对话特征

TODO
- [ ] 分析视频内容
- [ ] 发送语音
- [ ] 将禁言与解禁通知加入上下文 (notice.group_ban.ban/lift_ban)
- [ ] 将戳一戳通知加入上下文 (notice.notify.poke)
- [ ] 收到群成员名片修改通知修改缓存 (notice.group_card)
- [ ] 弃用 onebot v11 框架，使用 alconna