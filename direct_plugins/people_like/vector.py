from pydantic import BaseModel
from pymilvus import DataType, AsyncMilvusClient, MilvusClient
from datetime import datetime


class VectorData(BaseModel):
    id: int
    message_id: int
    group_id: int
    user_id: int
    index: int
    nick_name: str
    content: str
    vec: list[float]  # 向量数据，假设为浮点数列表
    time: int  # 时间戳


class MilvusVector:
    def __init__(self):
        self.collection_name = "people_like"
        self.client = MilvusClient(uri="http://localhost:19530")
        self.async_client = AsyncMilvusClient(uri="http://localhost:19530")

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
            schema.add_field("index", DataType.INT32)
            schema.add_field("nick_name", DataType.VARCHAR, max_length=255)
            schema.add_field("content", DataType.VARCHAR, max_length=1024)
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
            print(f"Collection '{self.collection_name}' created.")
        else:
            print(f"Collection '{self.collection_name}' already exists.")

    async def insert_data(self, data: list[VectorData]):
        data_dict = [item.model_dump() for item in data]
        res = await self.async_client.insert(collection_name=self.collection_name, data=data_dict)

    async def query_data(self, group_id: int, query_vector: list[float]) -> list[VectorData]:
        today_zero_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        expr = f"""
        group_id == {group_id} and time >= {today_zero_time}
        """
        results = await self.async_client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            expr=expr,
            output_fields=["id", "message_id", "group_id", "user_id", "index", "nick_name", "content", "vec", "time"],
            limit=5,  # 限制返回数量
            consistency_level="Strong",  # 强一致性
        )
        return [VectorData(**result) for result in results[0]] if results else []
