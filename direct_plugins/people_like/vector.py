from typing import Optional
from pydantic import BaseModel
from pymilvus import DataType, AsyncMilvusClient, MilvusClient
from datetime import datetime
from nonebot import logger


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


class MilvusVector:
    def __init__(
        self, uri: str, username: str, password: str, query_len: int = 10, search_len: int = 10, self_len: int = 3
    ):
        self.query_len = query_len
        self.search_len = search_len
        self.self_len = self_len
        self.collection_name = "people_like"
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

    async def insert_data(self, data: list[VectorData]):
        data_dict = [item.model_dump() for item in data]
        for d in data_dict:
            d.pop("id", None)
        res = await self.async_client.insert(collection_name=self.collection_name, data=data_dict)
        return res["insert_count"]

    async def query_data(self, group_id: int) -> list[VectorData]:
        expr = f"group_id == {group_id}"
        await self.async_client.load_collection(collection_name=self.collection_name)
        # 按时间戳降序排序（获取最新的消息）
        sort_key = [("time", "desc")]
        results = await self.async_client.query(
            collection_name=self.collection_name,
            filter=expr,
            sort_by=sort_key,
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
            consistency_level="Strong",
        )
        return [VectorData(**item) for item in results]

    async def query_self_data(self, group_id: int) -> list[VectorData]:
        today_zero_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        expr = f"group_id == {group_id} and self_msg == true and time >= {today_zero_time}"
        await self.async_client.load_collection(collection_name=self.collection_name)
        # 按时间戳降序排序（获取最新的消息）
        sort_key = [("time", "desc")]
        results = await self.async_client.query(
            collection_name=self.collection_name,
            filter=expr,
            sort_by=sort_key,
            output_fields=[
                # "id",
                # "message_id",
                # "group_id",
                # "user_id",
                # "self_msg",
                # "to_me",
                # "index",
                # "nick_name",
                "content",
                # "file_id",
                # "vec",
                # "time",
            ],
            limit=self.self_len,  # 限制返回数量
            consistency_level="Strong",
        )
        return [VectorData(**item) for item in results]

    async def search_data(self, group_id: int, query_vector: list[list[float]]) -> list[VectorData]:
        today_zero_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        expr = f"group_id == {group_id} and time >= {today_zero_time}"
        await self.async_client.load_collection(collection_name=self.collection_name)
        results = await self.async_client.search(
            collection_name=self.collection_name,
            data=query_vector,
            filter=expr,
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
            limit=self.search_len,  # 限制返回数量
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
