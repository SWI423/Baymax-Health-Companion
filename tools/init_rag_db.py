"""
RAG 知识库批量灌入工具
读取 data/knowledge_base.json 的 entries 数组，逐条向量化后存入 rag_knowledge 表。

用法：
    python tools/init_rag_db.py              # 批量灌入知识库
    python tools/init_rag_db.py --clear      # 灌入前先清空 rag_knowledge（去重重灌）
    python tools/init_rag_db.py --backfill   # 只为历史 memory_points / chat_long 补填向量
"""

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import console
from core import memory, rag

KB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "knowledge_base.json")


def load_entries():
    """从 knowledge_base.json 读取 entries，兼容纯字符串和 {text/content/knowledge} 对象两种格式"""
    if not os.path.exists(KB_PATH):
        console.error(f"找不到知识库文件：{KB_PATH}")
        return []

    with open(KB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    texts = []
    for e in entries:
        if isinstance(e, str):
            texts.append(e)
        elif isinstance(e, dict):
            t = e.get("text") or e.get("content") or e.get("knowledge")
            if t:
                texts.append(str(t))
    return texts


def ingest_knowledge(clear_first=False):
    """批量灌入知识库"""
    if clear_first:
        memory.clear_rag_entries()

    texts = load_entries()
    if not texts:
        console.warn("knowledge_base.json 中没有可灌入的知识条目（entries 为空）")
        return 0

    console.info(f"共读取 {len(texts)} 条知识，开始批量向量化灌入...")
    success = 0
    for i, t in enumerate(texts, 1):
        if rag.add_to_knowledge_base(t):
            success += 1
            console.rag(f"已录入 {i}/{len(texts)} · {t[:18]}")
        else:
            console.error(f"录入失败 {i}/{len(texts)} · {t[:18]}")

    total = len(memory.get_all_rag_entries())
    console.info(f"灌入完成：成功 {success}/{len(texts)} 条，知识库现存 {total} 条")
    return success


def main():
    console.banner("大白 RAG 知识库初始化工具")

    memory.init_db()

    if "--backfill" in sys.argv:
        # 补填历史记忆向量后退出
        memory.backfill_embeddings()
        return

    clear_first = "--clear" in sys.argv
    if clear_first:
        console.info("指定了 --clear，灌入前将清空旧知识库")

    ingest_knowledge(clear_first=clear_first)


if __name__ == "__main__":
    main()
