import json
from typing import Optional
from pydantic import BaseModel
from pymilvus import DataType, AsyncMilvusClient, MilvusClient
from nonebot import get_driver, logger
from google import genai
from google.genai.types import (
    Part,
    Content,
    GenerateContentConfig
)
from common import retry_on_exception

from .config import plugin_config

_GEMINI_CLIENT = genai.Client(
    api_key=plugin_config.gemini_key,
    http_options={
        "base_url": plugin_config.gemini_base_url,
        "api_version": "v1alpha",
        "timeout": 120_000,
        "headers": {"transport": "rest"},
    },
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

        self.collection_name_image = "people_like_image"

        self.client = MilvusClient(uri=uri, user=username, password=password)
        self.async_client = AsyncMilvusClient(uri=uri, user=username, password=password)
        # 创建集合
        self.create_collection()

    def create_collection(self):
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


    async def insert_image_data(self, data: list[VectorDataImage]):
        """插入数据到 Milvus 向量数据库 collection_name_image"""
        data_dict = [item.model_dump() for item in data]
        for d in data_dict:
            d.pop("id", None)
        res = await self.async_client.insert(collection_name=self.collection_name_image, data=data_dict)
        return res["insert_count"]

    async def query_image_data(self, file_id: str | list[str]) -> list[VectorDataImage]:
        exprs = []
        if isinstance(file_id, list):
            exprs.append(f"name in {repr(file_id)}")
        else:
            exprs.append(f"name == '{file_id}'")
        await self.async_client.load_collection(collection_name=self.collection_name_image)
        results = await self.async_client.query(
            collection_name=self.collection_name_image,
            filter=" and ".join(exprs),
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

    async def delete_image_data(self, file_id: str | list[str]) -> int:
        """删除 Milvus 向量数据库 collection_name_image 中的数据"""
        exprs = []
        if isinstance(file_id, list):
            exprs.append(f"name in {repr(file_id)}")
        else:
            exprs.append(f"name == '{file_id}'")
        await self.async_client.load_collection(collection_name=self.collection_name_image)
        res = await self.async_client.delete(
            collection_name=self.collection_name_image,
            filter=" and ".join(exprs),
        )
        return res["delete_count"]

@retry_on_exception(max_retries=5)
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


@retry_on_exception(max_retries=5)
async def analysis_image_to_str_description(parts: list[Part]) -> str:
    """分析图片，返回图片分析内容"""
    global _GEMINI_CLIENT
    response = await _GEMINI_CLIENT.aio.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[
            Content(
                role="user",
                parts=parts,
            )
        ],
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[str],
        ),
    )
    arr: list[str] = json.loads(str(response.text))

    return ",".join(arr) if arr else ""
