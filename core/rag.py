"""
RAG 检索增强生成模块
基于智谱 embedding-3 的文本向量化 + 余弦相似度检索。
知识库批量灌入/去重重灌请运行：python tools/init_rag_db.py
"""
import sys
import os
import json
import requests
import numpy as np
from core import console
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
    将一段文本转换为数学向量（智谱 embedding-3，默认 2048 维）
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
        console.error(f"向量化失败：{e}")
        return None


def add_to_knowledge_base(text: str):
    """
    把一条医疗知识写进 SQLite（带向量）。
    成功时静默（由调用方决定如何汇报），失败返回 False。
    """
    vec = get_embedding(text)
    if vec is None: return False

    # 把 numpy 数组转成普通的 list，再转成 JSON 字符串存进数据库
    vec_str = json.dumps(vec.tolist())
    memory.save_rag_entry(text, vec_str)
    return True


def search_knowledge_base(query: str, top_k=2, min_score=0.45):
    """
    用户提问时，在知识库里搜索最相关的 top_k 条记录。
    相似度低于 min_score 的不注入——低分知识进 Prompt 只是噪音，还会把回复带偏。
    终端只汇报命中条数和最高分，明细不打印。
    """
    # 1. 把用户的提问变成向量
    query_vec = get_embedding(query)
    if query_vec is None: return []

    # 2. 从数据库取出所有知识
    entries = memory.get_all_rag_entries()
    if not entries: return []

    # 3. 挨个算相似度
    scored_entries = []
    for entry in entries:
        emb_str = entry.get("embedding")
        if not emb_str:
            continue  # 跳过没有向量的历史数据
        try:
            # 把数据库里的字符串反解成 numpy 数组
            db_vec = np.array(json.loads(emb_str), dtype=np.float32)
        except Exception:
            continue  # 跳过损坏的向量数据

        # 算余弦相似度
        similarity = np.dot(query_vec, db_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(db_vec))
        scored_entries.append((similarity, entry["content"]))

    if not scored_entries:
        console.rag("知识库无可用向量数据")
        return []

    # 4. 按照相似度从高到低排序，先过低分阈值，再取前 top_k 个
    scored_entries.sort(key=lambda x: x[0], reverse=True)
    if not scored_entries or scored_entries[0][0] < min_score:
        console.debug(f"知识库最高分 {scored_entries[0][0]:.2f}，未过 {min_score} 阈值，本次不注入")
        return []
    results = scored_entries[:top_k]

    # 只汇报命中条数和最高分，保持终端干净
    console.rag(f"知识库命中 {len(results)} 条 · 最高 {results[0][0]:.2f}")

    return [text for score, text in results]


if __name__ == "__main__":
    # 初始化数据库表
    memory.init_db()

    # 1. 先录入几条医疗知识（快速冒烟测试；正式灌入请用 tools/init_rag_db.py）
    console.info("--- 正在录入知识 ---")
    for t in ["头晕时应立即坐下休息，避免摔倒。",
              "眼睛酸痛可以使用温毛巾热敷缓解。",
              "发烧超过38.5度建议服用退烧药并多喝水。",
              "咳嗽时多喝温水，保持室内空气湿润。"]:
        if add_to_knowledge_base(t):
            console.rag(f"已录入：{t}")

    # 2. 模拟用户提问检索
    console.info("--- 开始检索 ---")
    # 问1：天旋地转，与“头晕”语义匹配
    search_knowledge_base("我刚刚站起来，感觉天旋地转的")

    # 问2：眼睛不舒服，与“眼睛酸痛”匹配
    search_knowledge_base("盯电脑太久，眼球有点干涩胀痛")