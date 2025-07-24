# emoji.json 来源于 https://koishi.js.org/QFace/#/qqnt 

from httpx import get
from google import genai

from google.genai.types import (
    Part,
    Content,
    GenerateContentConfig
)

base_url = "https://koishi.js.org/QFace"

response = get(f"{base_url}/assets/qq_emoji/_index.json")
emoji_list = response.json()

GEMINI_CLIENT = genai.Client(
    api_key="114514",
    http_options={
        "api_version": "v1alpha",
        "timeout": 120_000,
        "headers": {"transport": "rest"},
    },
)

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

def analyze_emoji(emoji_url: str) -> str:
    """
    调用分析 emoji 表达的情感信息
    """
    suffix = emoji_url.split(".")[-1]
    match suffix:
        case "png":
            mime_type = "image/png"
        case _:
            mime_type = "image/jpeg"
    response = get(url=emoji_url)
    bytes = response.read()

    # 调用分析接口
    result = GEMINI_CLIENT.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[
            Content(
                role="user",
                parts=[
                    Part.from_text(text="请分析这个表情的情感信息，并给出简短的描述，字数在 5 以内，不要包含任何标点符号。"),
                    Part.from_bytes(data=bytes, mime_type=mime_type),
                ]
            )
        ],
        config=GenerateContentConfig(
            max_output_tokens=4
        )
    )
    return result.text.strip() # type: ignore

# 生成目标内容
lines = []
for item in emoji_list:
    emoji_id = str(item.get("emojiId", ""))
    describe: str = item.get("describe", "")
    describe = describe[1:] if describe.startswith("/") else describe
    if not describe and emoji_id in super_emoji_map:  # 如果没有描述，且是超级表情
        describe = super_emoji_map[emoji_id]
    if not describe and len(asset_list := [asset for asset in list(item.get("assets"))]) > 0:
        asset_list.sort(key=lambda x: x.get("type"))
        path = asset_list[0].get("path")
        url = f"{base_url}/{path}"
        # 调用分析接口
        describe = analyze_emoji(url)
        print(f"分析 emoji {emoji_id} 的描述: {describe}")

    lines.append(f"{emoji_id} {describe}".strip())

# 写入 emoji.txt
with open("emoji.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))