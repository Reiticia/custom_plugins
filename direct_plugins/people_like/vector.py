from typing import Optional
from pydantic import BaseModel
from pymilvus import DataType, AsyncMilvusClient, MilvusClient
from datetime import datetime
from nonebot import get_driver, logger
from google import genai
from google.genai.types import (
    Part,
    Content,
)

from .config import plugin_config

_GEMINI_CLIENT = genai.Client(
    api_key=plugin_config.gemini_key,
    http_options={"api_version": "v1alpha", "timeout": 120_000, "headers": {"transport": "rest"}},
)

driver = get_driver()

_MILVUS_VECTOR_CLIENT: Optional["MilvusVector"] = None


async def init_milvus_vector() -> "MilvusVector":
    """初始化 Milvus 向量数据库客户端"""
    global _MILVUS_VECTOR_CLIENT
    _MILVUS_VECTOR_CLIENT = MilvusVector(
        plugin_config.milvus.uri,
        plugin_config.milvus.username,
        plugin_config.milvus.password,
        plugin_config.query_len,
        plugin_config.search_len,
        plugin_config.self_len,
    )
    return _MILVUS_VECTOR_CLIENT


async def get_milvus_vector_client() -> "MilvusVector":
    """获取 Milvus 向量数据库客户端实例"""
    global _MILVUS_VECTOR_CLIENT
    if _MILVUS_VECTOR_CLIENT is None:
        return await init_milvus_vector()
    else:
        return _MILVUS_VECTOR_CLIENT


class VectorData(BaseModel):
    id: Optional[int] = None  # 自增主键
    message_id: Optional[int]
    group_id: Optional[int]
    user_id: Optional[int]
    self_msg: Optional[bool]  # 是否为自己的消息
    to_me: Optional[bool]  # 是否为提及自己的消息
    index: Optional[int]
    nick_name: Optional[str]
    content: Optional[str]
    file_id: Optional[str]
    vec: Optional[list[float]]  # 向量数据，假设为浮点数列表
    time: Optional[int]  # 时间戳

class VectorDataImage(BaseModel):
    id: Optional[int] = None  # 自增主键
    description: Optional[str]
    name: Optional[str]
    summary: Optional[str]
    mime_type: Optional[str]
    file_size: Optional[int]
    key: Optional[str]
    emoji_id: Optional[str]
    emoji_package_id: Optional[str]
    vec: Optional[list[float]]  # 向量数据，假设为浮点数列表
    extra: Optional[dict] = None  # 可选的额外信息

class MilvusVector:
    def __init__(
        self, uri: str, username: str, password: str, query_len: int = 10, search_len: int = 10, self_len: int = 3
    ):
        self.query_len = query_len
        self.search_len = search_len
        self.self_len = self_len
        self.collection_name = "people_like"

        self.collection_name_image = "people_like_image"

        self.client = MilvusClient(uri=uri, user=username, password=password)
        self.async_client = AsyncMilvusClient(uri=uri, user=username, password=password)
        # 创建集合
        self.create_collection()

    def create_collection(self):
        if not self.client.has_collection(self.collection_name):
            # 定义字段 Schema
            schema = self.client.create_schema(
                auto_id=True,  # 启用自增主键[3,4](@ref)
                enable_dynamic_field=False,
            )
            schema.add_field("id", DataType.INT64, is_primary=True)
            schema.add_field("message_id", DataType.INT64)
            schema.add_field("group_id", DataType.INT64)
            schema.add_field("user_id", DataType.INT64)
            schema.add_field("self_msg", DataType.BOOL, default=False)  # 是否为自己的消息
            schema.add_field("to_me", DataType.BOOL, default=False)  # 是否为提及自己的消息
            schema.add_field("index", DataType.INT32)
            schema.add_field("nick_name", DataType.VARCHAR, max_length=255)
            schema.add_field("content", DataType.VARCHAR, max_length=4096)
            schema.add_field("file_id", DataType.VARCHAR, max_length=1024)
            schema.add_field("vec", DataType.FLOAT_VECTOR, dim=768)  # 向量维度需自定义
            schema.add_field("time", DataType.INT64)
            schema.add_field("extra", DataType.JSON)

            # 创建索引参数（向量字段必建索引）
            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="vec",
                index_type="IVF_FLAT",  # 中等规模数据集推荐[3](@ref)
                metric_type="COSINE",  # 余弦相似度
                params={"nlist": 128},  # 聚类中心数
            )

            # 创建集合
            self.client.create_collection(
                collection_name=self.collection_name, schema=schema, index_params=index_params
            )
            logger.info(f"Collection '{self.collection_name}' created.")
        else:
            logger.info(f"Collection '{self.collection_name}' already exists.")

        # 创建图片集合
        if not self.client.has_collection(self.collection_name_image):
            schema = self.client.create_schema(
                auto_id=True,  # 启用自增主键[3,4](@ref)
                enable_dynamic_field=False,
            )
            schema.add_field("id", DataType.INT64, is_primary=True)
            schema.add_field("description", DataType.VARCHAR, max_length=8192)
            schema.add_field("name", DataType.VARCHAR, max_length=1024)
            schema.add_field("summary", DataType.VARCHAR, max_length=1024, nullable=True)
            schema.add_field("mime_type", DataType.VARCHAR, max_length=255)
            schema.add_field("file_size", DataType.INT64, nullable=True)  # 文件大小
            schema.add_field("key", DataType.VARCHAR, max_length=1024, nullable=True)
            schema.add_field("emoji_id", DataType.VARCHAR, max_length=255, nullable=True)
            schema.add_field("emoji_package_id", DataType.VARCHAR, max_length=255, nullable=True)
            schema.add_field("vec", DataType.FLOAT_VECTOR, dim=768)  # 向量维度需自定义
            schema.add_field("extra", DataType.JSON, nullable=True)

            # 创建索引参数（向量字段必建索引）
            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="vec",
                index_type="IVF_FLAT",  # 中等规模数据集推荐[3](@ref)
                metric_type="COSINE",  # 余弦相似度
                params={"nlist": 128},  # 聚类中心数
            )

            # 创建集合
            self.client.create_collection(
                collection_name=self.collection_name_image, schema=schema, index_params=index_params
            )
            logger.info(f"Collection '{self.collection_name_image}' created.")
        else:
            logger.info(f"Collection '{self.collection_name_image}' already exists.")



    async def insert_data(self, data: list[VectorData]):
        """插入数据到 Milvus 向量数据库 collection_name"""
        data_dict = [item.model_dump() for item in data]
        for d in data_dict:
            d.pop("id", None)
        res = await self.async_client.insert(collection_name=self.collection_name, data=data_dict)
        return res["insert_count"]
    
    async def insert_image_data(self, data: list[VectorDataImage]):
        """插入数据到 Milvus 向量数据库 collection_name_image"""
        data_dict = [item.model_dump() for item in data]
        for d in data_dict:
            d.pop("id", None)
        res = await self.async_client.insert(collection_name=self.collection_name_image, data=data_dict)
        return res["insert_count"]

    async def query_data(self, group_id: int = 0) -> list[VectorData]:
        exprs = []
        if group_id != 0:
            exprs.append(f"group_id == {group_id}")
        await self.async_client.load_collection(collection_name=self.collection_name)
        results = await self.async_client.query(
            collection_name=self.collection_name,
            filter=" and ".join(exprs),
            output_fields=[
                "id",
                "message_id",
                "group_id",
                "user_id",
                "self_msg",
                "to_me",
                "index",
                "nick_name",
                "content",
                "file_id",
                "vec",
                "time",
            ],
            limit=self.query_len,  # 限制返回数量
        )
        return [VectorData(**item) for item in results]

    async def query_self_data(self, group_id: int = 0) -> list[VectorData]:
        today_zero_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        exprs = []
        exprs.append("self_msg == true")  # 只查询自己的消息
        exprs.append(f"time >= {today_zero_time}")  # 只查询今天的
        if group_id != 0:
            exprs.append(f"group_id == {group_id}")
        await self.async_client.load_collection(collection_name=self.collection_name)
        results = await self.async_client.query(
            collection_name=self.collection_name,
            filter=" and ".join(exprs),
            output_fields=[
                "id",
                "message_id",
                "group_id",
                "user_id",
                "self_msg",
                "to_me",
                "index",
                "nick_name",
                "content",
                "file_id",
                "vec",
                "time",
            ],
            limit=self.self_len,  # 限制返回数量
        )
        return [VectorData(**item) for item in results]

    async def query_image_data(self, file_id: str|list[str]) -> list[VectorDataImage]:
        if isinstance(file_id, list):
            expr = f"name in {repr(file_id)}"
        else:
            expr = f"name == '{file_id}'"
        await self.async_client.load_collection(collection_name=self.collection_name_image)
        results = await self.async_client.query(
            collection_name=self.collection_name_image,
            filter=expr,
            output_fields=[
                "id",
                "description",
                "name",
                "summary",
                "mime_type",
                "file_size",
                "key",
                "emoji_id",
                "emoji_package_id",
                "vec",
                "extra",
            ],
            limit=self.query_len,  # 限制返回数量
        )
        return [VectorDataImage(**item) for item in results]

    async def search_data(
        self,
        query_vector: list[list[float]],
        file_ids: list[str] | bool = False,
        time_limit: int | bool = False,
        search_len: int = 0,
        group_id: int = 0
    ) -> list[VectorData]:
        today_zero_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        exprs: list[str] = []
        if time_limit:
            if isinstance(time_limit, bool) and time_limit:
                exprs.append(f"time >= {today_zero_time}")
            elif isinstance(time_limit, int):
                exprs.append(f"time >= {time_limit}")
        if group_id != 0:
            exprs.append(f"group_id == {group_id}")
        if file_ids:
            if isinstance(file_ids, bool) and file_ids:
                exprs.append("file_id != ''")
            elif isinstance(file_ids, list) and file_ids:
                exprs.append(f"file_id in {repr(file_ids)}")
        await self.async_client.load_collection(collection_name=self.collection_name)
        results = await self.async_client.search(
            collection_name=self.collection_name,
            data=query_vector,
            filter=" and ".join(exprs),
            search_params={
                "metric_type": "COSINE",
                "params": {
                    "nprobe": 128,  # 搜索空间大小（精度-性能平衡点）
                    "radius": 0.7,  # 最小相似度阈值（可选）
                },
            },
            output_fields=[
                "id",
                "message_id",
                "group_id",
                "user_id",
                "self_msg",
                "to_me",
                "index",
                "nick_name",
                "content",
                "file_id",
                "vec",
                "time",
            ],
            limit=self.search_len if search_len == 0 else search_len,  # 限制返回数量
            consistency_level="Strong",  # 强一致性
        )

        # 适配 Milvus 返回结构
        vector_data_list = []
        if results and len(results) > 0:
            for item in results[0]:
                # 如果是 entity 结构
                entity = item.get("entity", item)
                vector_data_list.append(VectorData(**entity))
        return vector_data_list
    
    async def search_image_data(
        self,
        query_vector: list[list[float]],
        file_id: str | bool = False,
        search_len: int = 0,
    ) -> list[VectorDataImage]:
        exprs: list[str] = []
        if file_id:
            if isinstance(file_id, bool) and file_id:
                exprs.append("name != ''")
            elif isinstance(file_id, str):
                exprs.append(f"name == '{file_id}'")
        await self.async_client.load_collection(collection_name=self.collection_name_image)
        results = await self.async_client.search(
            collection_name=self.collection_name_image,
            data=query_vector,
            filter=" and ".join(exprs),
            search_params={
                "metric_type": "COSINE",
                "params": {
                    "nprobe": 128,  # 搜索空间大小（精度-性能平衡点）
                    "radius": 0.7,  # 最小相似度阈值（可选）
                },
            },
            output_fields=[
                "id",
                "description",
                "name",
                "summary",
                "mime_type",
                "file_size",
                "key",
                "emoji_id",
                "emoji_package_id",
                "vec",
                "extra",
            ],
            limit=self.search_len if search_len == 0 else search_len,  # 限制返回数量
            consistency_level="Strong",  # 强一致性
        )
        # 适配 Milvus 返回结构
        vector_data_image_list = []
        if results and len(results) > 0:
            for item in results[0]:
                # 如果是 entity 结构
                entity = item.get("entity", item)
                vector_data_image_list.append(VectorDataImage(**entity))
        return vector_data_image_list



async def get_text_embedding(text: str) -> list[float]:
    """获取文本的向量表示"""
    global _GEMINI_CLIENT
    if not text:
        return []
    resp = await _GEMINI_CLIENT.aio.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
    embedding = resp.embeddings
    value = embedding[0].values if embedding else []
    return value if value else [0.0] * 768  # 假设向量维度为768，如果没有返回值则返回全0向量


async def analysis_image(parts: list[Part]) -> str:
    """分析图片，返回图片分析内容"""
    global _GEMINI_CLIENT
    response = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            Content(
                role="user",
                parts=parts,
            )
        ],
    )
    return response.text.strip() if response.text else ""
