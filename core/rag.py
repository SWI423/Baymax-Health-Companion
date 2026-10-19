"""
RAG 检索增强生成模块
第一步：实现文本向量化（Embedding）
"""
import sys
import os
import json
import requests
import numpy as np

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


if __name__ == "__main__":
    print("正在测试 Embedding 向量化...")

    # 测试句子1：用户说的话
    text1 = "我今天感觉天旋地转，好晕"
    # 测试句子2：医疗知识库里的内容
    text2 = "头晕时应立即坐下休息，避免摔倒"

    vec1 = get_embedding(text1)
    vec2 = get_embedding(text2)

    if vec1 is not None and vec2 is not None:
        print(f"\n✅ 向量化成功！")
        print(f"句子1向量长度: {len(vec1)}")
        print(f"句子1前5个数字: {vec1[:5]}")
        print(f"句子2前5个数字: {vec2[:5]}")

        # 计算两句话的相似度（余弦相似度公式）
        # 值越接近1，说明意思越相近
        similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
        print(f"\n🎯 两句话的语义相似度: {similarity:.4f}")