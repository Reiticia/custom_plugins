from google import genai


_GEMINI_CLIENT = genai.Client(
    api_key="AIzaSyC2TLax0ZSVMqswpf212WxF0RsoKxfL9Xs",
    http_options={"api_version": "v1alpha", "timeout": 120_000, "headers": {"transport": "rest"}},
)

image_list = _GEMINI_CLIENT.files.list()
count = 0
for file in image_list:
    _GEMINI_CLIENT.files.delete(name=file.name) # type: ignore
    count += 1


print(f"删除了 {count} 个文件")
