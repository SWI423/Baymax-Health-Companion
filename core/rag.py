"""
RAG 检索增强生成模块
第一步：实现文本向量化（Embedding）
"""
import sys
import os
import json
import requests
import numpy as np
from core import memory

# 将根目录加入路径，确保能导入 config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY

# 智谱 Embedding API 的地址（注意：不是对话的地址，专用于向量化）
EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
# 使用的模型
EMBEDDING_MODEL = "embedding-3"


def get_embedding(text: str) -> np.ndarray:
    """
    将一段文本转换为 1024 维的数学向量
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json; charset=utf-8"
    }

    data = {
        "model": EMBEDDING_MODEL,
        "input": text
    }

    try:
        # 发送请求
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        resp = requests.post(EMBEDDING_URL, headers=headers, data=payload)
        resp.raise_for_status()

        # 解析结果
        result = resp.json()
        embedding_list = result["data"][0]["embedding"]

        # 将 Python 列表转为 numpy 数组，方便后续做矩阵计算（比如算余弦相似度）
        return np.array(embedding_list, dtype=np.float32)

    except Exception as e:
        print(f"[RAG] 向量化失败：{e}")
        return None


def add_to_knowledge_base(text: str):
    """
    把一条医疗知识写进 SQLite（带向量）
    """
    vec = get_embedding(text)
    if vec is None: return False

    # 把 numpy 数组转成普通的 list，再转成 JSON 字符串存进数据库
    vec_str = json.dumps(vec.tolist())
    memory.save_rag_entry(text, vec_str)
    print(f"[RAG] 成功录入知识库: {text[:20]}...")
    return True


def search_knowledge_base(query: str, top_k=2):
    """
    用户提问时，在知识库里搜索最相关的 top_k 条记录
    """
    print(f"\n[RAG] 正在检索知识库，问题: {query}")

    # 1. 把用户的提问变成向量
    query_vec = get_embedding(query)
    if query_vec is None: return []

    # 2. 从数据库取出所有知识
    entries = memory.get_all_rag_entries()
    if not entries: return []

    # 3. 挨个算相似度
    scored_entries = []
    for entry in entries:
        # 把数据库里的字符串反解成 numpy 数组
        db_vec = np.array(json.loads(entry["embedding"]), dtype=np.float32)

        # 算余弦相似度
        similarity = np.dot(query_vec, db_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(db_vec))
        scored_entries.append((similarity, entry["content"]))

    # 4. 按照相似度从高到低排序，取前 top_k 个
    scored_entries.sort(key=lambda x: x[0], reverse=True)
    results = scored_entries[:top_k]

    # 打印检索结果（方便调试）
    for score, text in results:
        print(f"[RAG] 命中相似度 {score:.4f} -> {text}")

    return [text for score, text in results]


if __name__ == "__main__":
    # 初始化数据库表
    memory.init_db()

    # 1. 先录入几条医疗知识（模拟医疗知识库）
    print("--- 正在录入知识 ---")
    add_to_knowledge_base("头晕时应立即坐下休息，避免摔倒。")
    add_to_knowledge_base("眼睛酸痛可以使用温毛巾热敷缓解。")
    add_to_knowledge_base("发烧超过38.5度建议服用退烧药并多喝水。")
    add_to_knowledge_base("咳嗽时多喝温水，保持室内空气湿润。")

    # 2. 模拟用户提问检索
    print("\n--- 开始检索 ---")
    # 问1：天旋地转，与“头晕”语义匹配
    search_knowledge_base("我刚刚站起来，感觉天旋地转的")

    # 问2：眼睛不舒服，与“眼睛酸痛”匹配
    search_knowledge_base("盯电脑太久，眼球有点干涩胀痛")