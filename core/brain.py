"""
大白大脑 - 两次调用架构 + 事件队列
Pass 1：专心说话
Pass 2：后台提取（JSON），完成后 emotion 进队列

所有提示词来自 prompts.py，配置来自 config.py
"""

import re
import sys
import os
import json
import queue
import threading
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, API_URL, MODEL_NAME, LANGUAGE, Keywords
from prompts import (SYSTEM_PROMPT, EXTRACT_PROMPT,
                     SUMMARY_PROMPT_USER, SUMMARY_PROMPT_MEMORY, SUMMARY_PROMPT_LONG,
                     FEWSHOT_EXAMPLES)
from core import memory

_messages = []
MAX_MESSAGES = 20

VALID_EMOTIONS = {"neutral", "concern", "alert", "serious", "suspect", "sleepy"}

# ★ 事件队列：Pass 2 线程 → 主循环
emotion_queue = queue.Queue()


# ============================================================
# 构建提示词
# ============================================================
def _build_persona_prompt():
    prompt = SYSTEM_PROMPT

    if LANGUAGE == "自动":
        lang_note = "请使用与用户输入相同的语言回复。"
    else:
        lang_note = f"默认使用 {LANGUAGE} 回复用户。"

    prompt += f"""

【记忆规则】
用户问"你记得我什么""你记得我喜欢…吗"时，直接从资料层陈述你记得的内容，不要说"已记录"——"已记录"只用于确认新信息已存档。只能从【用户信息】【记忆点】【往日摘要】读取，不要从【相关历史】推断。

【输出语言】
{lang_note}

【输出要求】
自然说话，不要输出任何标签、记号或格式符号。
当用户要求你记住某事，或设置/修改/取消提醒时，用自然语言确认即可（如"已记录""好的，已设置"），后台会有另一个程序负责真正执行，你不需要做任何标记。
"""
    return prompt


def _build_data_context(user_input=None):
    sections = []

    profile = memory.get_user_profile()
    lines = []
    if profile.get("name"):     lines.append(f"- 名字：{profile['name']}")
    if profile.get("age"):      lines.append(f"- 年龄：{profile['age']}")
    if profile.get("birthday"): lines.append(f"- 生日：{profile['birthday']}")
    if profile.get("sibling"):  lines.append(f"- 兄弟姐妹：{profile['sibling']}")
    if lines:
        sections.append("【用户信息】\n" + "\n".join(lines))

    points = memory.get_memory_points_for_prompt(limit=10)
    if points:
        sections.append("【记忆点】\n" + "\n".join(f"- {p}" for p in points))

    summaries = memory.get_recent_summaries(limit=5)
    if summaries:
        text = "【往日摘要】\n"
        for s in summaries:
            text += f"- [{s['period_start']} ~ {s['period_end']}] {s['summary']}\n"
        sections.append(text.rstrip())

    health = memory.get_recent_health_events(5)
    if health:
        sections.append("【最近健康事件】\n" +
                        "\n".join(f"- {h['event_type']}: {h['detail']}" for h in health))

    reminders = memory.get_all_reminders()
    if reminders:
        text = "【当前所有提醒】\n"
        for r in reminders:
            status = {"active": "启用中", "cancelled": "已取消",
                      "completed": "已完成"}.get(r["status"], r["status"])
            text += f"- {r['event_name']}：{r['time']}，{status}\n"
        sections.append(text.rstrip())

    if user_input:
        related = memory.search_all_for_rag(user_input, limit=3)
        if related:
            text = "【相关历史】\n"
            for r in related:
                text += f"- [{r['source']}] {r['content']}\n"
            sections.append(text.rstrip())

    if not sections:
        return "（暂无用户资料记录）"
    return "以下是你记住的关于用户的资料，供你参考：\n\n" + "\n\n".join(sections)


_FIXED_HEAD = 2 + len(FEWSHOT_EXAMPLES) * 2


def _fresh_messages():
    msgs = [
        {"role": "system", "content": _build_persona_prompt()},
        {"role": "system", "content": _build_data_context()},
    ]
    for u, a in FEWSHOT_EXAMPLES:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    return msgs


def load_history():
    global _messages
    _messages = _fresh_messages()
    print("[brain] 历史卫生模式：不回灌原始对话")


def reset_history():
    global _messages
    _messages = _fresh_messages()


def _trim_messages():
    global _messages
    if len(_messages) > MAX_MESSAGES:
        _messages = _messages[:_FIXED_HEAD] + _messages[-(MAX_MESSAGES - _FIXED_HEAD):]


# ============================================================
# API 调用
# ============================================================
def _call_llm(messages, temperature, json_mode=False):
    headers = {"Authorization": f"Bearer {API_KEY}",
               "Content-Type": "application/json; charset=utf-8"}
    data = {"model": MODEL_NAME, "messages": messages, "temperature": temperature}
    if json_mode:
        data["response_format"] = {"type": "json_object"}
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    resp = requests.post(API_URL, headers=headers, data=payload)
    if resp.status_code != 200 and json_mode:
        data.pop("response_format", None)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        resp = requests.post(API_URL, headers=headers, data=payload)
    if resp.status_code != 200:
        print(f"[api] 失败 status={resp.status_code} body={resp.text[:200]}")
    resp.raise_for_status()
    stream = True
    return resp.json()["choices"][0]["message"]["content"]

def _call_llm_stream(messages, temperature):
    """流式调用大模型，逐段 yield 文本内容。
    用于 Pass 1 说话，实现打字机效果。
    """
    headers = {"Authorization": f"Bearer {API_KEY}",
               "Content-Type": "application/json; charset=utf-8"}
    data = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")

    resp = requests.post(API_URL, headers=headers, data=payload, stream=True)
    if resp.status_code != 200:
        print(f"[api] 流式失败 status={resp.status_code} body={resp.text[:200]}")
    resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        # 只处理 "data: xxx" 行
        if not line.startswith("data: "):
            continue
        data_str = line[6:]  # 去掉 "data: "
        if data_str.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content
        except (json.JSONDecodeError, KeyError, IndexError):
            # 跳过异常行，不中断流
            continue

# ============================================================
# Pass 2 提取
# ============================================================
def _parse_json_loose(text):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _extract_actions(user_input, reply):
    prompt = EXTRACT_PROMPT.format(user_input=user_input, reply=reply)
    try:
        raw = _call_llm([{"role": "user", "content": prompt}],
                        temperature=0.1, json_mode=True)
    except Exception as e:
        print(f"[pass2] 请求失败，本轮降级：{e}")
        return {"emotion": "neutral", "actions": []}
    result = _parse_json_loose(raw)
    if not isinstance(result, dict):
        print(f"[pass2] JSON 解析失败，本轮降级。原始输出：{raw[:100]}")
        return {"emotion": "neutral", "actions": []}
    emotion = str(result.get("emotion", "neutral")).lower()
    if emotion not in VALID_EMOTIONS:
        emotion = "neutral"
    actions = result.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    return {"emotion": emotion, "actions": actions}


def _normalize_time(t):
    if not t:
        return None
    t = str(t).strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.search(
        r"(早上|上午|中午|下午|晚上|今晚|明晚|凌晨|深夜|半夜)?(\d{1,2})[点:：](\d{1,2})?",
        t)
    if m:
        period = m.group(1) or ""
        hour = int(m.group(2))
        minute = m.group(3)
        if any(w in period for w in ("晚", "下")) and hour < 12:
            hour += 12
        return f"{hour:02d}:{int(minute) if minute else 0:02d}"
    return None


def _execute_actions(actions):
    for a in actions:
        if not isinstance(a, dict):
            continue
        atype = str(a.get("type", "")).upper()
        try:
            if atype == "SET_REMINDER":
                t = _normalize_time(a.get("time"))
                if a.get("event") and t:
                    memory.save_reminder(a["event"], t, a.get("frequency", "daily"))
                    print(f"[action] 设置提醒：{a['event']} @ {t}")
            elif atype == "UPDATE_REMINDER":
                t = _normalize_time(a.get("time"))
                if a.get("event") and t:
                    memory.update_reminder(a["event"], new_time=t)
                    print(f"[action] 更新提醒：{a['event']} @ {t}")
            elif atype == "CANCEL_REMINDER":
                if a.get("event"):
                    memory.cancel_reminder(a["event"])
                    print(f"[action] 取消提醒：{a['event']}")
            elif atype == "SAVE_MEMORY":
                if a.get("content"):
                    _save_memory_from_content(a["content"])
        except Exception as e:
            print(f"[action] 失败：{e}，原始：{a}")


# ============================================================
# Pass 2 线程 worker
# ============================================================
_PASS2_THREADS = []


def _pass2_worker(user_input, reply, holder):
    extracted = _extract_actions(user_input, reply)
    holder["emotion"] = extracted["emotion"]
    if extracted["actions"]:
        _execute_actions(extracted["actions"])
    # ★ 把 emotion 丢进事件队列（供主循环消费）
    emotion_queue.put(extracted["emotion"])
    print(f"[pass2] emotion={extracted['emotion']}，actions={len(extracted['actions'])}")


def wait_pending_pass2():
    for t in _PASS2_THREADS:
        t.join(timeout=10)


def get_pending_emotion():
    """主循环调用：从队列取出 emotion（非阻塞）"""
    try:
        return emotion_queue.get_nowait()
    except queue.Empty:
        return None


# ============================================================
# 核心：提问
# ============================================================
def ask_baymax(user_input, wait_pass2=False, on_chunk=None):
    """
    on_chunk: 可选回调，每收到一段文本调用一次。
              用于流式打印或未来更新 Pygame 屏幕文字。
    """
    global _messages

    if not user_input or not user_input.strip():
        return {"reply": "（等待输入）", "emotion": None}

    if len(_messages) < _FIXED_HEAD:
        _messages = _fresh_messages()
    _messages[0] = {"role": "system", "content": _build_persona_prompt()}
    _messages[1] = {"role": "system", "content": _build_data_context(user_input)}

    _messages.append({"role": "user", "content": user_input})
    memory.save_chat("user", user_input)

    # Pass 1：说话（流式）
    reply_parts = []
    try:
        for chunk in _call_llm_stream(_messages, temperature=0.9):
            reply_parts.append(chunk)
            if on_chunk:
                on_chunk(chunk)
        reply = "".join(reply_parts).strip()
    except Exception as e:
        return {"reply": f"大白卡住了... {e}", "emotion": "neutral"}

    holder = {}
    t = threading.Thread(target=_pass2_worker, args=(user_input, reply, holder))
    t.start()
    _PASS2_THREADS.append(t)

    _messages.append({"role": "assistant", "content": reply})
    memory.save_chat("assistant", reply)
    _trim_messages()

    if wait_pass2:
        t.join()
        emotion = holder.get("emotion", "neutral")
    else:
        emotion = None

    return {"reply": reply, "emotion": emotion}


# ============================================================
# 智能分表
# ============================================================
def _save_memory_from_content(content):
    saved = False

    if any(w in content for w in Keywords.NAME_HINTS) and not any(
            w in content for w in Keywords.SIBLING_HINTS):
        name = re.sub(r".*?叫(?:做)?", "", content)
        name = re.split(r"[，,。 ]", name)[0].strip()
        if name and not re.search(r"[\d岁]", name):
            memory.update_user_profile(name=name)
            print(f"[action] → user_profile.name: {name}")
            saved = True

    m = re.search(r"(\d+)\s*岁", content)
    if m:
        age = m.group(1) + "岁"
        memory.update_user_profile(age=age)
        print(f"[action] → user_profile.age: {age}")
        saved = True

    if any(w in content for w in Keywords.BIRTHDAY_HINTS):
        bday = re.sub(r".*?生日(?:是|为)?", "", content).strip("，,。 ")
        if bday:
            memory.update_user_profile(birthday=bday)
            print(f"[action] → user_profile.birthday: {bday}")
            saved = True

    if any(w in content for w in Keywords.SIBLING_HINTS):
        memory.update_user_profile(sibling=content)
        print(f"[action] → user_profile.sibling: {content}")
        saved = True

    if saved:
        return
    memory.save_memory_point(content, source="user_command", importance=8)
    print(f"[action] → memory_points: {content}")


# ============================================================
# 摘要任务
# ============================================================
def do_summary():
    chats = memory.get_unsummarized_chats()
    if len(chats) < 10:
        print(f"[brain] 未总结对话仅 {len(chats)} 条，跳过摘要")
        return

    dialog = "\n".join(f"{c['role']}: {c['content']}" for c in chats)
    period_start = chats[0]["timestamp"][:10]
    period_end = chats[-1]["timestamp"][:10]

    def call_llm(prompt):
        return _call_llm([{"role": "user", "content": prompt}], temperature=0.3)

    # 用户信息
    try:
        r1 = call_llm(SUMMARY_PROMPT_USER.format(dialog=dialog))
        for m in re.finditer(r"\[USER:(\w+)\](.+)", r1):
            field = m.group(1).strip()
            value = m.group(2).strip()
            if field in ["name", "age", "birthday", "sibling"]:
                if value and value not in Keywords.PLACEHOLDER_VALUES:
                    memory.update_user_profile(**{field: value})
    except Exception as e:
        print(f"[摘要] 用户信息提取失败：{e}")

    # 记忆 + 健康
    try:
        r2 = call_llm(SUMMARY_PROMPT_MEMORY.format(dialog=dialog))
        m = re.search(r"\[MEMORY\](.+?)(?=\n\[|\n\n|$)", r2, re.DOTALL)
        if m:
            content = m.group(1).strip()
            memory.save_memory_point(content, source="ai_summary", importance=5)
            print(f"[摘要] 记忆点：{content[:50]}...")
        m = re.search(r"\[HEALTH\](.+?)(?=\n\[|\n\n|$)", r2, re.DOTALL)
        if m:
            content = m.group(1).strip()
            memory.save_health_event("summary", content)
            print(f"[摘要] 健康：{content[:50]}...")
    except Exception as e:
        print(f"[摘要] 记忆+健康提取失败：{e}")

    # 长对话摘要
    try:
        r3 = call_llm(SUMMARY_PROMPT_LONG.format(dialog=dialog))
        memory.save_chat_summary(period_start, period_end, r3.strip())
        print(f"[摘要] 长期摘要已保存：{period_start} ~ {period_end}")
    except Exception as e:
        print(f"[摘要] 长对话摘要失败：{e}")

    chat_ids = [c["id"] for c in chats]
    memory.mark_chats_summarized(chat_ids)
    memory.delete_summarized_chats(chat_ids)
    print(f"[brain] 摘要完成，共处理 {len(chats)} 条对话")


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    memory.init_db()
    load_history()
    print("=== 大白大脑测试（two-call + 事件队列） ===")
    print("输入 '退出' 结束，'做摘要' 触发摘要\n")

    while True:
        user_text = input("你：")
        if user_text == "退出":
            wait_pending_pass2()
            print("大白：再见。")
            break
        if user_text == "做摘要":
            do_summary()
            continue
        print("大白：", end="", flush=True)
        result = ask_baymax(
            user_text,
            on_chunk=lambda c: print(c, end="", flush=True)
        )
        print()  # 流式结束后换行
        wait_pending_pass2()