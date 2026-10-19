"""
大白大脑 - LangChain
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
from core import console
from core import memory
from core.rag import search_knowledge_base

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, API_URL, MODEL_NAME, LANGUAGE, Keywords, QUICK_CONCERN_KEYWORDS
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


def predict_emotion_quick(user_input):
    """
    输入即刻预判：在调用大模型之前，根据关键词立即给出情绪标签。
    随后 Pass 2 提取到的精准情绪会覆盖它（见 state_machine.handle_chat）。
    """
    if not user_input:
        return None
    for kw in QUICK_CONCERN_KEYWORDS:
        if kw in user_input:
            return "concern"
    return None


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
用户问"你记得我什么""你记得我喜欢…吗"时，直接从资料层陈述你记得的内容，不要说"已记录"——"已记录"只用于确认新信息已存档。只能从【用户信息】【记忆点】【往日摘要】读取，不要从【相关历史与记忆】推断。

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
        # 混合检索：短期原话（chat_short 最近几句）+ 长期语义记忆（向量余弦相似度）
        recent_chats = memory.get_recent_chats(limit=3)
        related_memories = memory.search_long_term_memory_by_vector(user_input, limit=3)
        if recent_chats or related_memories:
            text = "【相关历史与记忆】\n"
            if recent_chats:
                text += "近期对话原话：\n"
                for c in recent_chats:
                    speaker = "用户" if c["role"] == "user" else "大白"
                    text += f"- {speaker}: {c['content']}\n"
            if related_memories:
                text += "深层语义记忆（向量检索）：\n"
                for m in related_memories:
                    text += f"- [{m['source']}] {m['content']}\n"
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
    console.debug("LangChain 版本启动，历史卫生模式已开启")


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


# ============================================================
# Pass 2 记忆清洗：只放行"用户真说过"的内容
# 事故背景：提取器曾把大白的反问/建议/安慰包装成"用户询问/用户提到"存进记忆库，
# 污染语义检索。提示词负责教，这里负责拦——按子句做字面追溯，
# 在用户原话里找不到依据的一律丢弃（宁可漏存，不可错存）。
# ============================================================
_PUNCT_RE = re.compile(r"[，。！？、,.!?\s\u3000；;\"'“”‘’]")
# 记忆句式的模板前缀（追溯判定时剥掉，存储时保留）
_PREFIX_RE = re.compile(r"^(用户)?(表示|提到|询问|反映|认为|说明|声称|感觉)?")

def _bigrams(s):
    """文本的二字组集合（剥掉标点后计算，跨标点拼接）"""
    s = _PUNCT_RE.sub("", str(s))
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}

def _trace_score(content, text):
    """content 的二字组有多大比例能在 text 中找到（0~1）"""
    bg = _bigrams(_PREFIX_RE.sub("", str(content)))
    if not bg:
        return 0.0
    return len(bg & _bigrams(text)) / len(bg)

def _sanitize_memory_content(content, user_input):
    """
    清洗一条 SAVE_MEMORY 内容：
    - 按标点拆子句，逐句验证能否在用户原话里找到字面依据
    - 找不到依据的子句丢弃（几乎全是大白的话或模型的引申）
    - 所有子句都无依据 → 返回 None（整条丢弃）
    """
    content = str(content).strip().rstrip("。")
    if not content:
        return None
    clauses = [c.strip() for c in re.split(r"[，,；;。]", content) if c.strip()]
    if len(clauses) <= 1:
        return content if _trace_score(content, user_input) >= 0.2 else None
    kept = [c for c in clauses if _trace_score(c, user_input) >= 0.2]
    return "，".join(kept) if kept else None

def _sanitize_memory_actions(actions, user_input, reply):
    """
    对 Pass 2 提取出的动作做入库前清洗，返回清洗后的 actions：
    1. 用户原话里毫无字面依据 → 丢弃（大白的话或幻觉）
    2. 逐子句剥离无依据部分（模型的引申在这里被切掉）
    3. 批次内去重 + 与最近 30 条已有记忆去重
    注：不按【大白的回复】追溯——回复本来就会复述用户的事实
    （如"找实习和准备软考确实耗费精力"），按它判定会误杀真记忆。
    """
    existing = memory.get_memory_points_for_prompt(limit=30)
    existing_bg = [_bigrams(p) for p in existing]
    seen = set()
    cleaned = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        if str(a.get("type", "")).upper() != "SAVE_MEMORY":
            cleaned.append(a)
            continue
        raw = a.get("content")
        if not raw:
            continue
        if _trace_score(raw, user_input) < 0.1:
            console.debug(f"[过滤] 用户原话中无依据：{raw}")
            continue
        content = _sanitize_memory_content(raw, user_input)
        if not content:
            console.debug(f"[过滤] 各子句均无依据：{raw}")
            continue
        key = _PUNCT_RE.sub("", content)
        if key in seen:
            continue
        seen.add(key)
        bg = _bigrams(content)
        if any(len(bg & e) / max(1, len(bg | e)) >= 0.6 for e in existing_bg):
            console.debug(f"[过滤] 与已有记忆重复：{content}")
            continue
        cleaned.append({"type": "SAVE_MEMORY", "content": content})
    return cleaned


def _pass2_worker(user_input, reply):
    extracted = _extract_actions(user_input, reply)
    # 👈 入库前清洗：拦掉大白的话、模型的引申和重复记忆
    extracted["actions"] = _sanitize_memory_actions(extracted["actions"], user_input, reply)
    if extracted["actions"]:
        _execute_actions(extracted["actions"])
        console.action(f"后台执行 {len(extracted['actions'])} 项操作")
    emotion_queue.put(extracted["emotion"])
    # 情绪由状态机层汇报，这里只留调试明细
    console.debug(f"pass2 emotion={extracted['emotion']}")


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
        if on_chunk:
            print()  # 收尾流式回复，避免后台日志粘在回复行尾
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
            console.error(f"后台动作失败：{e}")


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
        console.action(f"已记住：{content}")
    else:
        console.action("用户资料已更新")


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
        ask_baymax(user_text, wait_pass2=False, on_chunk=lambda c: print(c, end="", flush=True))
        print()
        wait_pending_pass2()