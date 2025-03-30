from pymilvus import AsyncMilvusClient, CollectionSchema, DataType, FieldSchema
from asyncio import sleep

from pymilvus.milvus_client import IndexParams
from .image_send import _GEMINI_CLIENT

from nonebot import logger, get_driver

_MILVUS_CLIENT = AsyncMilvusClient(uri="http://localhost:19530")

_FIELDS = [
    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
    FieldSchema(name="group_id", dtype=DataType.INT64),
    FieldSchema(name="user_id", dtype=DataType.INT64),
    FieldSchema(name="nickname", dtype=DataType.VARCHAR, max_length=30),
    FieldSchema(name="is_bot", dtype=DataType.BOOL),
    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=500),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=64),
    FieldSchema(name="insert_time", dtype=DataType.INT64),  # 使用 INT64 存储时间戳（毫秒）
]

schema = CollectionSchema(fields=_FIELDS, description="people_like vector database")

driver = get_driver()


@driver.on_bot_connect
async def create_db():
    try:
        await _MILVUS_CLIENT.create_collection(collection_name="people_like", schema=schema)
        logger.info("Create collection successfully")
        # 创建索引
        idx = IndexParams()
        idx.add_index(field_name="group_id", index_type="STL_SORT", index_name="group_id_index")
        idx.add_index(
            field_name="embedding", index_type="IVF_FLAT", index_name="embedding_index", params={"nlist": 1024}
        )
        await _MILVUS_CLIENT.create_index(collection_name="people_like", index_params=idx)

    except Exception as e:
        logger.error(f"Create collection failed: {e}")


async def add_content(group_id: int, user_id: int, nickname: str, text: str, time: int, is_bot: bool = False):
    """添加一条数据记录到表

    Args:
        group_id (int): 群号
        text (str): 文本内容
    """

    line = {
        "group_id": group_id,
        "user_id": user_id,
        "nickname": nickname,
        "is_bot": is_bot,
        "text": text,
        "embedding": await get_embedding(text),
        "insert_time": time,
    }

    # 插入数据
    await _MILVUS_CLIENT.insert(collection_name="people_like", data=line)


async def get_embedding(text: str):
    return (
        await _GEMINI_CLIENT.aio.models.embed_content(
            model="gemini-embedding-exp-03-07", contents=text, config={"output_dimensionality": 64}
        )
    ).embeddings


async def search_content(group_id: int, text: str):
    """搜索相关内容

    Args:
        group_id (int): 群号
        text (str): 文本内容
    """
    text_embedding = await get_embedding(text)
    results = await _MILVUS_CLIENT.search(
        collection_name="people_like",
        data=[text_embedding],
        anns_field="embedding",
        expr=f"group_id == {group_id}",  # 过滤指定群组
        param={"metric_type": "L2", "params": {"nprobe": 20}},
        limit=10,  # 获取前 10 相似结果用于后续排序
        output_fields=["text", "insert_time"],  # 返回需要展示的字段
    )

    sorted_hits = sorted(
        results[0],
        key=lambda x: x.entity.insert_time,  # type: ignore
        reverse=True,  # 降序（最新在前）
    )[:10]  # 取前 10 个结果

    sorted_hits = sorted(sorted_hits, key=lambda x: x.entity.insert_time, reverse=True)  # type: ignore

    return [hit.entity.text for hit in sorted_hits]  # type: ignore
