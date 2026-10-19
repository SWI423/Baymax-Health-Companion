"""
大白大脑 - LangChain 企业级架构版本
- Pass 1：基于 LCEL (LangChain Expression Language) 流式说话
- Pass 2：保留原生 JSON 提取（为了极高的稳定性）
- 保留：事件队列、智能分表、记忆系统、摘要系统
"""

import re
import sys
import os
import json
import queue
import threading
import requests
from core import memory
from core.rag import search_knowledge_base

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, API_URL, MODEL_NAME, LANGUAGE, Keywords
from prompts import (SYSTEM_PROMPT, EXTRACT_PROMPT,
                     SUMMARY_PROMPT_USER, SUMMARY_PROMPT_MEMORY, SUMMARY_PROMPT_LONG,
                     FEWSHOT_EXAMPLES)

# ==========================================
# 引入 LangChain 核心组件
# ==========================================
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

# 初始化企业级模型
llm = ChatOpenAI(
    api_key=API_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4/",
    model=MODEL_NAME,
    temperature=0.9,
    streaming=True
)

# 构建 LCEL 提示词模板
prompt_template = ChatPromptTemplate.from_messages([
    ("system", "{persona}"),
    ("system", "{context}"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{input}")
])

# 组装 LCEL 链：Prompt -> LLM -> 字符串解析
conversation_chain = prompt_template | llm | StrOutputParser()

_messages = []
MAX_MESSAGES = 20
VALID_EMOTIONS = {"neutral", "concern", "alert", "serious", "suspect", "sleepy"}
emotion_queue = queue.Queue()


# ============================================================
# 构建提示词与上下文
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
自然说话，不要输出任何标签、记号或格式符号。当用户要求你记住某事，或设置/修改/取消提醒时，用自然语言确认即可，后台会有另一个程序负责真正执行。
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
    if lines: sections.append("【用户信息】\n" + "\n".join(lines))

    points = memory.get_memory_points_for_prompt(limit=10)
    if points: sections.append("【记忆点】\n" + "\n".join(f"- {p}" for p in points))

    summaries = memory.get_recent_summaries(limit=5)
    if summaries:
        text = "【往日摘要】\n"
        for s in summaries:
            text += f"- [{s['period_start']} ~ {s['period_end']}] {s['summary']}\n"
        sections.append(text.rstrip())

    health = memory.get_recent_health_events(5)
    if health:
        sections.append("【最近健康事件】\n" + "\n".join(f"- {h['event_type']}: {h['detail']}" for h in health))

    reminders = memory.get_all_reminders()
    if reminders:
        text = "【当前所有提醒】\n"
        for r in reminders:
            status = {"active": "启用中", "cancelled": "已取消", "completed": "已完成"}.get(r["status"], r["status"])
            text += f"- {r['event_name']}：{r['time']}，{status}\n"
        sections.append(text.rstrip())

    if user_input:
        related = memory.search_all_for_rag(user_input, limit=3)
        if related:
            text = "【相关历史】\n"
            for r in related: text += f"- [{r['source']}] {r['content']}\n"
            sections.append(text.rstrip())

        medical_knowledge = search_knowledge_base(user_input, top_k=2)
        if medical_knowledge:
            text = "【参考医疗知识】\n"
            for k in medical_knowledge: text += f"- {k}\n"
            sections.append(text.rstrip())

    return "以下是你记住的关于用户的资料，供你参考：\n\n" + "\n\n".join(sections) if sections else "（暂无用户资料记录）"


# ============================================================
# 历史管理
# ============================================================
_FIXED_HEAD = 2 + len(FEWSHOT_EXAMPLES) * 2


def _convert_history_to_lc(msgs):
    """将字典列表转为 LangChain Message 对象"""
    lc_msgs = []
    for m in msgs:
        if m["role"] == "user":
            lc_msgs.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_msgs.append(AIMessage(content=m["content"]))
    return lc_msgs


def _fresh_messages():
    msgs = []
    for u, a in FEWSHOT_EXAMPLES:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    return msgs


def load_history():
    global _messages
    _messages = _fresh_messages()
    print("[brain] LangChain 版本启动，历史卫生模式已开启")


def _trim_messages():
    global _messages
    if len(_messages) > MAX_MESSAGES:
        _messages = _messages[-(MAX_MESSAGES):]


# ============================================================
# 原生非流式调用 (专供 Pass 2 提取和摘要)
# ============================================================
def _call_llm(messages, temperature, json_mode=False):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json; charset=utf-8"}
    data = {"model": MODEL_NAME, "messages": messages, "temperature": temperature}
    if json_mode: data["response_format"] = {"type": "json_object"}

    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    resp = requests.post(API_URL, headers=headers, data=payload)
    if resp.status_code != 200 and json_mode:
        data.pop("response_format", None)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        resp = requests.post(API_URL, headers=headers, data=payload)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _extract_actions(user_input, reply):
    prompt = EXTRACT_PROMPT.format(user_input=user_input, reply=reply)
    try:
        raw = _call_llm([{"role": "user", "content": prompt}], temperature=0.1, json_mode=True)
        result = json.loads(raw)
    except Exception as e:
        # 兜底：宽松解析
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            result = json.loads(m.group(0)) if m else {}
        except:
            result = {}

    emotion = str(result.get("emotion", "neutral")).lower()
    if emotion not in VALID_EMOTIONS: emotion = "neutral"
    actions = result.get("actions", [])
    if not isinstance(actions, list): actions = []
    return {"emotion": emotion, "actions": actions}


def _pass2_worker(user_input, reply):
    extracted = _extract_actions(user_input, reply)
    if extracted["actions"]: _execute_actions(extracted["actions"])
    emotion_queue.put(extracted["emotion"])
    print(f"[pass2] emotion={extracted['emotion']}，actions={len(extracted['actions'])}")


# ============================================================
# 核心入口：提问
# ============================================================
def ask_baymax(user_input, wait_pass2=False, on_chunk=None):
    global _messages
    if not user_input or not user_input.strip():
        return {"reply": "（等待输入）", "emotion": None}

    # 1. 构建 Prompt 变量
    inputs = {
        "persona": _build_persona_prompt(),
        "context": _build_data_context(user_input),
        "history": _convert_history_to_lc(_messages),
        "input": user_input
    }

    # 2. LCEL 链式调用流式输出
    reply_parts = []
    try:
        # chain.stream() 自动处理流式响应
        for chunk in conversation_chain.stream(inputs):
            reply_parts.append(chunk)
            if on_chunk: on_chunk(chunk)
        reply = "".join(reply_parts).strip()
    except Exception as e:
        return {"reply": f"大白卡住了... {e}", "emotion": "neutral"}

    # 3. 保存对话历史
    _messages.append({"role": "user", "content": user_input})
    _messages.append({"role": "assistant", "content": reply})
    memory.save_chat("user", user_input)
    memory.save_chat("assistant", reply)
    _trim_messages()

    # 4. 异步 Pass 2
    t = threading.Thread(target=_pass2_worker, args=(user_input, reply))
    t.start()
    _PASS2_THREADS.append(t)

    if wait_pass2:
        t.join()
        emotion = "neutral"
        while not emotion_queue.empty():
            emotion = emotion_queue.get()
    else:
        emotion = None

    return {"reply": reply, "emotion": emotion}


# ============================================================
# 智能分表与动作执行
# ============================================================
_PASS2_THREADS = []


def _execute_actions(actions):
    for a in actions:
        if not isinstance(a, dict): continue
        atype = str(a.get("type", "")).upper()
        try:
            if atype == "SET_REMINDER":
                t = _normalize_time(a.get("time"))
                if a.get("event") and t: memory.save_reminder(a["event"], t, a.get("frequency", "daily"))
            elif atype == "UPDATE_REMINDER":
                t = _normalize_time(a.get("time"))
                if a.get("event") and t: memory.update_reminder(a["event"], new_time=t)
            elif atype == "CANCEL_REMINDER":
                if a.get("event"): memory.cancel_reminder(a["event"])
            elif atype == "SAVE_MEMORY":
                if a.get("content"): _save_memory_from_content(a["content"])
        except Exception as e:
            print(f"[action] 失败：{e}")


def _normalize_time(t):
    if not t: return None
    t = str(t).strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", t)
    if m: return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.search(r"(早上|上午|中午|下午|晚上|今晚|明晚|凌晨|深夜|半夜)?(\d{1,2})[点:：](\d{1,2})?", t)
    if m:
        period, hour, minute = m.group(1) or "", int(m.group(2)), m.group(3)
        if any(w in period for w in ("晚", "下")) and hour < 12: hour += 12
        return f"{hour:02d}:{int(minute) if minute else 0:02d}"
    return None


def _save_memory_from_content(content):
    saved = False
    if any(w in content for w in Keywords.NAME_HINTS) and not any(w in content for w in Keywords.SIBLING_HINTS):
        name = re.sub(r".*?叫(?:做)?", "", content)
        name = re.split(r"[，,。 ]", name)[0].strip()
        if name and not re.search(r"[\d岁]", name):
            memory.update_user_profile(name=name);
            saved = True
    if "生日" in content:
        bday = re.sub(r".*?生日(?:是|为)?", "", content).strip("，,。 ")
        if bday: memory.update_user_profile(birthday=bday); saved = True
    if re.search(r"\d+\s*岁", content):
        age = re.search(r"\d+\s*岁", content).group(0)
        memory.update_user_profile(age=age);
        saved = True
    if any(w in content for w in Keywords.SIBLING_HINTS):
        memory.update_user_profile(sibling=content);
        saved = True

    if not saved:
        memory.save_memory_point(content, source="user_command", importance=8)
        print(f"[action] → memory_points: {content}")
    else:
        print(f"[action] → user_profile 已更新")


def wait_pending_pass2():
    for t in _PASS2_THREADS: t.join(timeout=10)


def get_pending_emotion():
    try:
        return emotion_queue.get_nowait()
    except queue.Empty:
        return None


# ============================================================
# 摘要任务 (沿用原生调用)
# ============================================================
def do_summary():
    chats = memory.get_unsummarized_chats()
    if len(chats) < 10: return

    dialog = "\n".join(f"{c['role']}: {c['content']}" for c in chats)
    period_start, period_end = chats[0]["timestamp"][:10], chats[-1]["timestamp"][:10]

    def call_llm(prompt):
        return _call_llm([{"role": "user", "content": prompt}], temperature=0.3)

    try:
        r1 = call_llm(SUMMARY_PROMPT_USER.format(dialog=dialog))
        for m in re.finditer(r"\[USER:(\w+)\](.+)", r1):
            field, value = m.group(1).strip(), m.group(2).strip()
            if field in ["name", "age", "birthday", "sibling"] and value not in Keywords.PLACEHOLDER_VALUES:
                memory.update_user_profile(**{field: value})
    except:
        pass

    try:
        r2 = call_llm(SUMMARY_PROMPT_MEMORY.format(dialog=dialog))
        m = re.search(r"\[MEMORY\](.+?)(?=\n\[|\n\n|$)", r2, re.DOTALL)
        if m: memory.save_memory_point(m.group(1).strip(), source="ai_summary", importance=5)
        m = re.search(r"\[HEALTH\](.+?)(?=\n\[|\n\n|$)", r2, re.DOTALL)
        if m: memory.save_health_event("summary", m.group(1).strip())
    except:
        pass

    try:
        r3 = call_llm(SUMMARY_PROMPT_LONG.format(dialog=dialog))
        memory.save_chat_summary(period_start, period_end, r3.strip())
    except:
        pass

    chat_ids = [c["id"] for c in chats]
    memory.mark_chats_summarized(chat_ids)
    memory.delete_summarized_chats(chat_ids)


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    memory.init_db()
    load_history()
    print("=== 大白大脑测试（LangChain 企业级架构） ===")
    while True:
        user_text = input("\n你：")
        if user_text == "退出":
            wait_pending_pass2()
            break
        if user_text == "做摘要":
            do_summary()
            continue

        print("大白：", end="", flush=True)
        ask_baymax(user_text, on_chunk=lambda c: print(c, end="", flush=True))
        print()