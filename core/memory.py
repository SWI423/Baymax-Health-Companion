"""
大白记忆系统 - 7 张表，分三层记忆架构。

语义记忆：user_profile、memory_points（带向量）、health_log
情景记忆：chat_short、chat_long（带向量）
工作记忆：reminders
RAG扩展：rag_knowledge

记忆点与长期摘要存入时同步写入 embedding 向量，
检索时用 search_long_term_memory_by_vector 做余弦相似度语义检索。
"""

import sqlite3
import os
import sys
import json
import re
from datetime import datetime, date

import numpy as np

from core import console

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_PATH


def _get_conn():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    return sqlite3.connect(DATABASE_PATH)


def init_db():
    conn = _get_conn()
    c = conn.cursor()

    # 表1：用户信息
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id     TEXT PRIMARY KEY,
            name        TEXT,
            age         TEXT,
            birthday    TEXT,
            health_id   TEXT,
            sibling     TEXT,
            updated_at  TIMESTAMP
        )
    """)

    # 表2：记忆点（embedding 存 1024 维向量的 JSON 字符串）
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory_points (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT,
            source      TEXT,
            importance  INTEGER DEFAULT 5,
            embedding   TEXT,
            created_at  TIMESTAMP
        )
    """)

    # 表3：短期对话
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_short (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role        TEXT,
            content     TEXT,
            timestamp   TIMESTAMP,
            summarized  INTEGER DEFAULT 0
        )
    """)

    # 表4：长期摘要（embedding 存摘要文本的向量 JSON 字符串）
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_long (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT,
            period_end   TEXT,
            summary      TEXT,
            embedding    TEXT,
            created_at   TIMESTAMP
        )
    """)

    # 表5：健康记录
    c.execute("""
        CREATE TABLE IF NOT EXISTS health_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT,
            detail      TEXT,
            timestamp   TIMESTAMP
        )
    """)

    # 表6：定时提醒（date：NULL=每日循环；具体日期=一次性提醒 once）
    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name      TEXT,
            time            TEXT,
            frequency       TEXT,
            date            TEXT,
            status          TEXT DEFAULT 'active',
            last_triggered  TIMESTAMP,
            created_at      TIMESTAMP
        )
    """)

    # 表7：RAG 医疗知识库 (必须放在 commit 之前)
    c.execute("""
        CREATE TABLE IF NOT EXISTS rag_knowledge (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT,
            embedding   TEXT,
            created_at  TIMESTAMP
        )
    """)

    # 平滑迁移：旧数据库的 memory_points / chat_long 自动补 embedding 字段（无需删库重建）
    _migrate_embedding_columns(c)
    # 平滑迁移：旧版 reminders 表自动补 date 字段（旧提醒默认每日，date=NULL）
    _migrate_reminder_date_column(c)

    conn.commit()
    conn.close()
    console.debug("数据库初始化完成，7 张表已就绪")


def _migrate_reminder_date_column(cursor=None):
    """旧版 reminders 表（无 date 列）自动补列；旧提醒保持每日循环（date=NULL）"""
    own_conn = cursor is None
    if own_conn:
        conn = _get_conn()
        c = conn.cursor()
    else:
        c = cursor
    c.execute("PRAGMA table_info(reminders)")
    cols = [row[1] for row in c.fetchall()]
    if "date" not in cols:
        c.execute("ALTER TABLE reminders ADD COLUMN date TEXT")
        console.info("reminders 表已自动补充 date 字段（旧提醒视为每日循环）")
    if own_conn:
        conn.commit()
        conn.close()


def _migrate_embedding_columns(cursor=None):
    """
    为已存在的旧库平滑补充 embedding 字段。
    旧数据不会丢失；没有向量的历史记录会在语义检索时被跳过，
    可用 backfill_embeddings() 事后补填。
    """
    own_conn = cursor is None
    if own_conn:
        conn = _get_conn()
        c = conn.cursor()
    else:
        c = cursor

    for table in ("memory_points", "chat_long"):
        c.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in c.fetchall()]
        if "embedding" not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN embedding TEXT")
            console.info(f"{table} 表已自动补充 embedding 字段（旧数据保留）")

    if own_conn:
        conn.commit()
        conn.close()


# ============================================================
# 表1：用户信息
# ============================================================
def _ensure_user(user_id="default"):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_profile WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        health_id = f"U{datetime.now().strftime('%Y%m%d%H%M%S')}"
        c.execute("""
            INSERT INTO user_profile (user_id, health_id, updated_at)
            VALUES (?, ?, ?)
        """, (user_id, health_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def update_user_profile(user_id="default", **fields):
    _ensure_user(user_id)
    allowed = {"name", "age", "birthday", "sibling"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [datetime.now().isoformat(), user_id]
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE user_profile SET {set_clause}, updated_at = ? WHERE user_id = ?", values)
    conn.commit()
    conn.close()
    console.info(f"用户信息已更新：{'、'.join(updates.keys())}")


def get_user_profile(user_id="default"):
    _ensure_user(user_id)
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, name, age, birthday, health_id, sibling
        FROM user_profile WHERE user_id = ?
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    if not row: return {}
    return {"user_id": row[0], "name": row[1], "age": row[2], "birthday": row[3], "health_id": row[4], "sibling": row[5]}


# ============================================================
# 表2：记忆点
# ============================================================
# 记忆来源 → 重要性（用户主动要求记住 > 大白自动记住 > 摘要记住）
_SOURCE_IMPORTANCE = {
    "user_require": 10,
    "user_command": 10,   # 旧数据源名，视同要求记住
    "user_auto": 5,
    "auto": 5,
    "summary": 3,
}


def _source_importance(source):
    return _SOURCE_IMPORTANCE.get(str(source), 5)


def save_memory_point(content, source="user_auto", importance=None):
    """
    记忆写入：查重 + 来源优先级覆盖（问题4方案）。
    同内容已存在时：
      - 已有记忆级别 ≥ 新记忆级别 → 跳过（不覆盖；用户主动要求的记忆最准确，不被低级覆盖）
      - 新记忆级别更高 → 覆盖（更新内容/来源/重要性/向量/时间）
    无重复 → 正常插入。
    """
    from core.rag import get_embedding  # 延迟导入，避免与 rag 模块循环依赖

    if importance is None:
        importance = _source_importance(source)

    norm = re.sub(r"\s+", "", str(content)).strip()
    conn = _get_conn()
    c = conn.cursor()

    # 查重（规范化文本完全匹配；语义层由检索去重）
    c.execute("SELECT id, content, importance FROM memory_points")
    for rid, old_content, old_imp in c.fetchall():
        if re.sub(r"\s+", "", old_content or "") == norm:
            conn.close()
            if old_imp >= importance:
                console.debug(f"[记忆] 已有更高/同级记忆，跳过覆盖：{str(content)[:20]}")
                return False
            # 新记忆级别更高 → 覆盖
            vec = None
            try:
                v = get_embedding(content)
                if v is not None:
                    vec = json.dumps(v.tolist())
            except Exception as e:
                console.warn(f"记忆点向量化失败（内容仍会保存）：{e}")
            conn = _get_conn()
            c = conn.cursor()
            c.execute("UPDATE memory_points SET content=?, source=?, importance=?, embedding=?, created_at=? WHERE id=?",
                      (content, source, importance, vec, datetime.now().isoformat(), rid))
            conn.commit()
            conn.close()
            console.debug(f"[记忆] 高优先级覆盖：{str(content)[:20]}")
            return True

    # 无重复 → 插入
    embedding_str = None
    try:
        vec = get_embedding(content)
        if vec is not None:
            embedding_str = json.dumps(vec.tolist())
    except Exception as e:
        console.warn(f"记忆点向量化失败（内容仍会保存）：{e}")

    c.execute("""
        INSERT INTO memory_points (content, source, importance, embedding, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (content, source, importance, embedding_str, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True


def get_all_memory_points():
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT id, content, source, importance, created_at FROM memory_points ORDER BY importance DESC, id ASC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "source": r[2], "importance": r[3], "created_at": r[4]} for r in rows]


def get_memory_points_for_prompt(limit=10):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT content FROM memory_points ORDER BY importance DESC, id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def delete_memory_points(ids):
    """按 ID 批量删除记忆点（清理错误提取的垃圾记忆），返回实际删除条数"""
    if not ids:
        return 0
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"DELETE FROM memory_points WHERE id IN ({','.join('?' * len(ids))})", list(ids))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


# ============================================================
# 表3：短期对话
# ============================================================
def save_chat(role, content):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO chat_short (role, content, timestamp) VALUES (?, ?, ?)", (role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_recent_chats(limit=20):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_short ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def get_unsummarized_chats():
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT id, role, content, timestamp FROM chat_short WHERE summarized = 0 ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "role": r[1], "content": r[2], "timestamp": r[3]} for r in rows]


def mark_chats_summarized(chat_ids):
    if not chat_ids: return
    conn = _get_conn()
    c = conn.cursor()
    ph = ",".join("?" * len(chat_ids))
    c.execute(f"UPDATE chat_short SET summarized = 1 WHERE id IN ({ph})", chat_ids)
    conn.commit()
    conn.close()


def delete_summarized_chats(chat_ids):
    if not chat_ids: return
    conn = _get_conn()
    c = conn.cursor()
    ph = ",".join("?" * len(chat_ids))
    c.execute(f"DELETE FROM chat_short WHERE id IN ({ph})", chat_ids)
    conn.commit()
    conn.close()
    console.debug(f"已删除 {len(chat_ids)} 条已总结的对话")


# ============================================================
# 表4：长期摘要
# ============================================================
def save_chat_summary(period_start, period_end, summary):
    from core.rag import get_embedding  # 延迟导入，避免与 rag 模块循环依赖

    # 存入摘要时顺便把摘要文本转成向量，失败不阻塞内容保存
    embedding_str = None
    try:
        vec = get_embedding(summary)
        if vec is not None:
            embedding_str = json.dumps(vec.tolist())
    except Exception as e:
        console.warn(f"摘要向量化失败（内容仍会保存）：{e}")

    conn = _get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO chat_long (period_start, period_end, summary, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
              (period_start, period_end, summary, embedding_str, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_recent_summaries(limit=5):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT period_start, period_end, summary FROM chat_long ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"period_start": r[0], "period_end": r[1], "summary": r[2]} for r in rows]


# ============================================================
# 表5：健康记录
# ============================================================
def save_health_event(event_type, detail=""):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO health_log (event_type, detail, timestamp) VALUES (?, ?, ?)", (event_type, detail, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_recent_health_events(limit=5):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT event_type, detail, timestamp FROM health_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"event_type": r[0], "detail": r[1], "timestamp": r[2]} for r in rows]


# ============================================================
# 表6：定时提醒
# ============================================================
def save_reminder(event_name, time_str, frequency="daily", date=None):
    existing = get_reminder(event_name)
    conn = _get_conn()
    c = conn.cursor()
    if existing and existing["status"] == "active":
        c.execute("UPDATE reminders SET time = ?, frequency = ?, date = ?, status = 'active' WHERE event_name = ?",
                  (time_str, frequency, date, event_name))
    else:
        c.execute("INSERT INTO reminders (event_name, time, frequency, date, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
                  (event_name, time_str, frequency, date, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_reminder(event_name):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT id, event_name, time, frequency, date, status, last_triggered, created_at FROM reminders WHERE event_name = ?", (event_name,))
    row = c.fetchone()
    conn.close()
    if not row: return None
    return {"id": row[0], "event_name": row[1], "time": row[2], "frequency": row[3], "date": row[4], "status": row[5], "last_triggered": row[6], "created_at": row[7]}


def get_all_reminders(only_active=False):
    conn = _get_conn()
    c = conn.cursor()
    if only_active:
        c.execute("SELECT id, event_name, time, frequency, date, status, last_triggered, created_at FROM reminders WHERE status='active' ORDER BY time ASC")
    else:
        c.execute("SELECT id, event_name, time, frequency, date, status, last_triggered, created_at FROM reminders ORDER BY time ASC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "event_name": r[1], "time": r[2], "frequency": r[3], "date": r[4], "status": r[5], "last_triggered": r[6], "created_at": r[7]} for r in rows]


def update_reminder(event_name, new_time=None, new_frequency=None, new_date=None):
    conn = _get_conn()
    c = conn.cursor()
    if new_time:
        c.execute("UPDATE reminders SET time = ? WHERE event_name = ?", (new_time, event_name))
    if new_frequency:
        c.execute("UPDATE reminders SET frequency = ? WHERE event_name = ?", (new_frequency, event_name))
    if new_date is not None:
        c.execute("UPDATE reminders SET date = ? WHERE event_name = ?", (new_date, event_name))
    conn.commit()
    conn.close()


def cancel_reminder(event_name):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("UPDATE reminders SET status = 'cancelled' WHERE event_name = ?", (event_name,))
    conn.commit()
    conn.close()


def mark_reminder_triggered(event_name):
    conn = _get_conn()
    c = conn.cursor()
    c.execute("UPDATE reminders SET last_triggered = ? WHERE event_name = ?", (datetime.now().isoformat(), event_name))
    conn.commit()
    conn.close()


def complete_reminder(event_name):
    """一次性提醒（once）触发后置为 done：保留历史记录，不再参与调度"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("UPDATE reminders SET status = 'done', last_triggered = ? WHERE event_name = ?",
              (datetime.now().isoformat(), event_name))
    conn.commit()
    conn.close()


def get_missed_reminders():
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    missed = []
    for r in get_all_reminders(only_active=True):
        if r["time"] <= now:
            last = r["last_triggered"]
            if not last or not last.startswith(today):
                missed.append({"event_name": r["event_name"], "time": r["time"]})
    return missed


# ============================================================
# 关键词检索 (旧的伪RAG，保留作为备用)
# ============================================================
def search_all_for_rag(keyword, limit=3):
    results = []
    conn = _get_conn()
    c = conn.cursor()

    c.execute("SELECT role, content FROM chat_short WHERE content LIKE ? ORDER BY id DESC LIMIT ?", (f"%{keyword}%", limit))
    for role, content in c.fetchall():
        results.append({"source": "short", "content": f"{role}: {content}"})

    c.execute("SELECT summary FROM chat_long WHERE summary LIKE ? ORDER BY id DESC LIMIT ?", (f"%{keyword}%", limit))
    for (s,) in c.fetchall():
        results.append({"source": "long", "content": s})

    c.execute("SELECT content FROM memory_points WHERE content LIKE ? ORDER BY importance DESC LIMIT ?", (f"%{keyword}%", limit))
    for (s,) in c.fetchall():
        results.append({"source": "memory", "content": s})

    conn.close()
    return results


# ============================================================
# 向量语义检索（真 RAG：余弦相似度，替代关键词 LIKE）
# ============================================================
def _cosine_similarity(vec_a, vec_b):
    """计算两个 numpy 向量的余弦相似度，零向量返回 0"""
    denom = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def search_long_term_memory_by_vector(query, limit=3, threshold=0.5):
    """
    长期记忆向量语义检索：
    把用户提问转成向量，与 memory_points 和 chat_long 里存的向量算余弦相似度，
    返回相似度 > threshold 的前 limit 条记录（按分数降序）。
    没有向量的历史数据自动跳过（可用 backfill_embeddings 补填）。
    """
    from core.rag import get_embedding  # 延迟导入，避免循环依赖

    query_vec = get_embedding(query)
    if query_vec is None:
        console.warn("提问向量化失败，本次跳过语义记忆检索")
        return []

    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT id, content, embedding FROM memory_points WHERE embedding IS NOT NULL AND embedding != ''")
    point_rows = c.fetchall()
    c.execute("SELECT id, summary, embedding FROM chat_long WHERE embedding IS NOT NULL AND embedding != ''")
    summary_rows = c.fetchall()
    conn.close()

    scored = []
    for row in point_rows:
        try:
            vec = np.array(json.loads(row[2]), dtype=np.float32)
        except Exception:
            continue
        score = _cosine_similarity(query_vec, vec)
        if score > threshold:
            scored.append({"source": "memory", "content": row[1], "score": round(score, 4)})

    for row in summary_rows:
        try:
            vec = np.array(json.loads(row[2]), dtype=np.float32)
        except Exception:
            continue
        score = _cosine_similarity(query_vec, vec)
        if score > threshold:
            scored.append({"source": "long", "content": row[1], "score": round(score, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    results = scored[:limit]

    if results:
        # 只汇报命中条数和最高分，明细不打印
        console.mem(f"{len(results)} 最高{results[0]['score']:.2f}")
    else:
        console.mem("0")
    return results


def backfill_embeddings():
    """为历史遗留的、没有向量的 memory_points / chat_long 记录补填向量"""
    from core.rag import get_embedding  # 延迟导入，避免循环依赖

    conn = _get_conn()
    c = conn.cursor()
    filled = 0
    for table, col in (("memory_points", "content"), ("chat_long", "summary")):
        c.execute(f"SELECT id, {col} FROM {table} WHERE embedding IS NULL OR embedding = ''")
        for row_id, text in c.fetchall():
            if not text:
                continue
            vec = get_embedding(text)
            if vec is None:
                continue
            c.execute(f"UPDATE {table} SET embedding = ? WHERE id = ?",
                      (json.dumps(vec.tolist()), row_id))
            filled += 1
    conn.commit()
    conn.close()
    console.info(f"向量补填完成，共更新 {filled} 条历史记录")
    return filled


def count_unsummarized_chats():
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM chat_short WHERE summarized = 0")
    count = c.fetchone()[0]
    conn.close()
    return count


# ============================================================
# 表7：RAG 知识库读写 (新加入)
# ============================================================
def save_rag_entry(content, embedding_str):
    """保存一条知识库记录及其向量"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO rag_knowledge (content, embedding, created_at)
        VALUES (?, ?, ?)
    """, (content, embedding_str, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_all_rag_entries():
    """读取知识库所有记录（用于计算相似度）"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT id, content, embedding FROM rag_knowledge")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "embedding": r[2]} for r in rows]


def clear_rag_entries():
    """清空知识库全部记录（配合 init_rag_db.py --clear 去重重灌）"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM rag_knowledge")
    conn.commit()
    conn.close()
    console.info("知识库已清空")


if __name__ == "__main__":
    init_db()
    print("用户信息：", get_user_profile())
    print("记忆点数量：", len(get_all_memory_points()))