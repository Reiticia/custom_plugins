# emoji.json 来源于 https://koishi.js.org/QFace/#/qqnt 

import json

# 读取 super_emojis.txt，建立 id->描述 的映射
super_emoji_map = {}
with open("no_deploy/ban_super_emoji/super_emojis.txt", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            super_emoji_map[parts[0]] = parts[1]

# 读取 emoji.json
with open("emoji.json", encoding="utf-8") as f:
    emoji_list = json.load(f)

# 生成目标内容
lines = []
for item in emoji_list:
    emoji_id = str(item.get("emojiId", ""))
    describe = item.get("describe", "")
    if not describe and emoji_id in super_emoji_map:
        describe = super_emoji_map[emoji_id]
    lines.append(f"{emoji_id} {describe}".strip())

# 写入 emoji.txt
with open("emoji.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))