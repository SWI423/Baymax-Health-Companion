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
from datetime import datetime, timedelta
from core import console
from core import memory
from core.rag import search_knowledge_base

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, API_URL, MODEL_NAME, LANGUAGE, Keywords, QUICK_CONCERN_KEYWORDS, QUICK_SERIOUS_KEYWORDS
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
    # temperature 0.7：高温度会放大模型"热情助人+格式化输出"的先验（编号清单泛滥），
    # 降温提升指令遵循；诙谐由人设与 few-shot 示范保证，不依赖随机性
    temperature=0.7,
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

# 动作队列：异步判断（如理由考察 accept/reject）的结果由 worker 线程投递，
# 主循环统一消费执行状态切换 —— 保证所有状态变更都发生在主循环单线程内
action_queue = queue.Queue()


def queue_action(action):
    """线程安全地投递一个待主循环执行的异步动作"""
    action_queue.put(action)


def get_current_time_context():
    """大白的时间感知：注入当前年月日 + 星期 + 时刻（设定提醒时用于理解相对日期）"""
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"现在是{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]} {now.strftime('%H:%M')}"


def resolve_relative_date(text, now=None):
    """
    把用户口头日期换算成 YYYY-MM-DD：
      - 今天/明天/后天/大后天
      - 下周一~下周日（指下周的周X）
      - YYYY-MM-DD / YYYY年M月D日 具体日期
    无法识别返回 None（由调用方回退为每日提醒）
    """
    if not text:
        return None
    t = str(text).strip()
    now = now or datetime.now()
    today = now.date()
    if "今天" in t:
        return today.isoformat()
    if "明天" in t:
        return (today + timedelta(days=1)).isoformat()
    if "后天" in t:
        return (today + timedelta(days=2)).isoformat()
    if "大后天" in t:
        return (today + timedelta(days=3)).isoformat()
    m = re.search(r"下(?:个)?(?:星期|周)([一二三四五六日天])", t)
    if m:
        idx = "一二三四五六日".find(m.group(1))
        if idx < 0:
            return None
        # 本周的周X → +7 即下周的周X
        days_ahead = (idx - now.weekday()) % 7 + 7
        return (today + timedelta(days=days_ahead)).isoformat()
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", t)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            return None
    return None


def judge_reason(user_text):
    """
    理由考察（状态图 S6/S7 的"大模型判断理由"）：
    用户在提醒/催促下说还没完成并给了理由，判断理由是否充分。
    返回 "accept"（允许不完成）或 "reject"（继续督促+开导）；
    调用失败时保守返回 "reject"（提醒主题优先，不让提醒丢失）。
    """
    prompt = (
        "你是大白，用户的私人健康助理。用户在提醒催促下说还没完成，并给了理由。\n"
        f"【用户的回应】{user_text}\n\n"
        "判断这个理由是否充分：\n"
        "- accept：理由真实且充分（身体不适、临时突发状况、任务已无意义等）→ 允许不完成\n"
        "- reject：理由牵强、拖延、逃避（懒得做、忘了、不想等）→ 应继续督促并开导\n"
        "只输出一个词：accept 或 reject。"
    )
    try:
        resp = requests.post(
            API_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL_NAME, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
            timeout=20,
        )
        data = resp.json()
        verdict = data["choices"][0]["message"]["content"].strip().lower()
        if "accept" in verdict:
            return "accept"
        return "reject"
    except Exception as e:
        console.error(f"理由考察失败（保守判 reject）：{e}")
        return "reject"


def predict_emotion_quick(user_input):
    """
    输入即刻预判：在调用大模型之前，根据关键词立即给出情绪标签。
    随后 Pass 2 提取到的精准情绪会覆盖它（见 state_machine.handle_chat）。
    优先级：concern（健康关切）> serious（严肃/硬撑）> neutral。
    """
    if not user_input:
        return None
    for kw in QUICK_CONCERN_KEYWORDS:
        if kw in user_input:
            return "concern"
    for kw in QUICK_SERIOUS_KEYWORDS:
        if kw in user_input:
            return "serious"
    return None


# ============================================================
# 催促场景三分类快判（状态图 E10 确认完成 / E11 给理由）
# ============================================================
# 否定/未完成词优先（"还没完成"绝不能误判成"完成"）
QUICK_NOT_COMPLETED_KEYWORDS = [
    "还没", "没完成", "没有", "没做完", "还没好", "还没做完",
    "再等", "等一下", "马上", "快了", "别催", "别急", "稍等",
    "给我点时间", "等一会", "等会儿", "再给我", "还在做", "正在", "还没呢",
]
QUICK_COMPLETED_KEYWORDS = [
    "完成", "好了", "搞定", "可以了", "做完", "结束", "好啦",
    "没问题", "成功", "哦了", "弄完", "干完", "搞完",
]


def predict_completion_quick(user_input):
    """
    催促场景回应三分类快判：
      - "completed"      → 用户确认完成（状态图 E10）
      - "not_completed"  → 用户给理由/还没完成（状态图 E11，由大模型判断接受与否）
      - None             → 闲聊/无法快判 → 交给大模型正常对话
    否定优先：先扫"还没/没完成"再扫"完成"，避免反义误判。
    """
    if not user_input:
        return None
    t = str(user_input)
    for kw in QUICK_NOT_COMPLETED_KEYWORDS:
        if kw in t:
            return "not_completed"
    for kw in QUICK_COMPLETED_KEYWORDS:
        if kw in t:
            return "completed"
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

【当前时间】
{get_current_time_context()}
用户提到"明天""后天""下周""几月几号"等设定提醒时，据此理解相对日期，并在 SET_REMINDER 的 date 字段里写出相对词或具体日期。

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


# 模块装载即注入 few-shot：运行链（main→state_machine→ask_baymax）不经过 __main__，
# 历史上 few-shot 从未生效，导致反导师腔/换框等行为缺少正向示范兜底
load_history()


def _trim_messages():
    global _messages
    if len(_messages) > MAX_MESSAGES:
        # 保护队首 few-shot（行为示范），只裁剪中间的历史对话
        head = _messages[:_FIXED_HEAD]
        tail = _messages[-(MAX_MESSAGES - _FIXED_HEAD):]
        _messages = head + tail


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

# 引申性评价词黑名单：这些词出现在记忆里、但用户原话没说过时，
# 几乎一定是模型把大白的话或自己的评价包装成了"用户态度"
# （如用户只说"我焦虑实习和软考"，记忆写成"用户重视实习和软考"）
_INFERENCE_WORDS = ("重视", "愿意", "有价值", "很重要", "渴求", "期待", "在乎", "决心")

def _has_unsourced_inference(clause, user_input):
    """子句里是否含有'用户没说过'的引申性评价词"""
    return any(w in clause and w not in user_input for w in _INFERENCE_WORDS)

def _sanitize_memory_content(content, user_input):
    """
    清洗一条 SAVE_MEMORY 内容：
    - 按标点拆子句，逐句验证能否在用户原话里找到字面依据
    - 找不到依据的子句丢弃（几乎全是大白的话或模型的引申）
    - 含引申性评价词的子句丢弃（大白提议/模型态度的包装）
    - 所有子句都无依据 → 返回 None（整条丢弃）
    """
    content = str(content).strip().rstrip("。")
    if not content:
        return None
    clauses = [c.strip() for c in re.split(r"[，,；;。]", content) if c.strip()]
    if len(clauses) <= 1:
        if _trace_score(content, user_input) >= 0.2 and not _has_unsourced_inference(content, user_input):
            return content
        return None
    kept = [c for c in clauses
            if _trace_score(c, user_input) >= 0.2 and not _has_unsourced_inference(c, user_input)]
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
        # 来源分级：用户主动要求记住 > 大白自动记住（问题4：要求记住最准确，优先级最高）
        src = "user_require" if any(k in user_input for k in ("记住", "记一下", "记着", "别忘了", "帮我记", "记下来")) else "user_auto"
        cleaned.append({"type": "SAVE_MEMORY", "content": content, "source": src})
    return cleaned


def _pass2_worker(user_input, reply):
    extracted = _extract_actions(user_input, reply)
    # 👈 入库前清洗：拦掉大白的话、模型的引申和重复记忆
    extracted["actions"] = _sanitize_memory_actions(extracted["actions"], user_input, reply)
    if extracted["actions"]:
        _execute_actions(extracted["actions"])
        console.action(f"操作 执行 {len(extracted['actions'])} 项")
    emotion_queue.put(extracted["emotion"])
    # 情绪由状态机层汇报，这里只留调试明细
    console.debug(f"pass2 emotion={extracted['emotion']}")


# ============================================================
# 格式守卫：导师腔的最后一道防线（代码层，确定性）
# 背景：GLM 对"该怎么办/有什么建议"类输入有极强的编号清单先验，
# prompt 层（顶部禁令+示范+降温）能压大部分但压不死。这里做确定性兜底：
# 流式回复完成后检测，命中格式违规 → 带修正指令重写一次（非流式）；
# 重写版仍违规则保留原版（不无限重试）。违规模不写进对话历史。
# ============================================================
_FORMAT_VIOLATION_PATTERNS = [
    (re.compile(r"(?m)^\s*\d+\s*[.、）)]\s*\S"), "编号列表"),
    (re.compile(r"(?m)^\s*[-*•]\s+\S"), "项目符号列表"),
    (re.compile(r"第[一二三四五六七八九十]步"), "步骤编排"),
    (re.compile(r"以下[是有几][^\n。]{0,8}(建议|方法|步骤)"), "清单导语"),
]

def _find_format_violation(text):
    """返回第一个命中的违规类型名，无违规返回 None"""
    for rx, name in _FORMAT_VIOLATION_PATTERNS:
        if rx.search(text or ""):
            return name
    return None

def _rewrite_without_list(user_input, bad_reply):
    """带修正指令让模型重写（非流式一次性调用，低温求稳）"""
    instruction = (
        "你刚才的回复出现了列表/步骤编排，这违反了你作为大白的第一铁律。"
        "请用大白的方式重写：禁编号列表、禁项目符号、禁「第X步/首先/然后/最后」、禁「以下是…建议」导语；"
        "先接住对方的情绪，然后像聊天一样说出你的看法，最多点一个具体的方法。"
        "只输出重写后的回复本身，不要任何解释。"
    )
    msgs = [
        {"role": "system", "content": _build_persona_prompt()},
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": bad_reply},
        {"role": "user", "content": instruction},
    ]
    return _call_llm(msgs, temperature=0.5).strip()


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

    # 2.5 格式守卫：命中导师腔格式 → 重写一次并播放重写版
    violation = _find_format_violation(reply)
    if violation:
        try:
            rewritten = _rewrite_without_list(user_input, reply)
            if rewritten and len(rewritten) >= 20 and not _find_format_violation(rewritten):
                if on_chunk:
                    on_chunk("\n\n——等一下，我重新说：\n")
                    for i in range(0, len(rewritten), 6):
                        on_chunk(rewritten[i:i + 6])
                reply = rewritten
                console.debug(f"[格式守卫] 命中「{violation}」，已重写")
        except Exception as e:
            console.debug(f"[格式守卫] 重写失败，保留原版：{e}")

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
                if a.get("event") and t:
                    date_word = a.get("date") or ""
                    if date_word:
                        # 相对日期 → 具体日期（明天/下周一/几月几号），换算成功为一次性提醒
                        d = resolve_relative_date(date_word)
                        if d:
                            memory.save_reminder(a["event"], t, frequency="once", date=d)
                            console.action(f"定时提醒 已设定：{a['event']} {t}（{d}）")
                            continue
                    memory.save_reminder(a["event"], t, a.get("frequency", "daily"))
                    console.action(f"定时提醒 已设定：{a['event']} {t}")
            elif atype == "UPDATE_REMINDER":
                t = _normalize_time(a.get("time"))
                if a.get("event") and t: memory.update_reminder(a["event"], new_time=t)
            elif atype == "CANCEL_REMINDER":
                if a.get("event"): memory.cancel_reminder(a["event"])
            elif atype == "SAVE_MEMORY":
                if a.get("content"):
                    _save_memory_from_content(a["content"], source=a.get("source", "user_auto"))
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


def _parse_name(content):
    """
    从记忆内容解析用户名字（问题3修复：Pass2 输出"用户叫小陈/用户的名字是小陈"格式，
    旧正则只认"我叫"格式导致名字没进 user_profile）。
    返回名字字符串，解析失败返回 None。
    """
    patterns = [
        # "用户的名字是小陈" / "名字是小陈" / "名字叫小陈"
        r"(?:用户|我)?的?名字(?:是|为|叫)?[\s:：]*([^\s，,。!！?？]{1,8})",
        # "用户叫小陈" / "我叫小陈" / "名叫小陈" / "小陈"（记忆点本身）
        r"(?:用户|我|你)?\s*(?:叫|名叫|叫做)\s*([^\s，,。!！?？]{1,8})",
    ]
    for p in patterns:
        m = re.search(p, content)
        if m:
            name = m.group(1).strip()
            # 排除数字/岁数/称谓词混入
            if name and not re.search(r"[\d岁]|用户|同学|朋友|兄弟|姐妹|名字|称呼", name):
                return name
    return None


def _save_memory_from_content(content, source="user_auto"):
    """
    保存一条记忆：① 个人信息（名字/生日/年龄/家人）同步更新 user_profile；
    ② 统一写入记忆点（带来源与重要性，查重+优先级覆盖见 memory.save_memory_point）。
    """
    saved = False
    if not any(w in content for w in Keywords.SIBLING_HINTS):
        name = _parse_name(content)
        if name:
            memory.update_user_profile(name=name)
            saved = True
    if "生日" in content:
        bday = re.sub(r".*?生日(?:是|为)?", "", content).strip("，,。 ")
        if bday: memory.update_user_profile(birthday=bday); saved = True
    if re.search(r"\d+\s*岁", content):
        age = re.search(r"\d+\s*岁", content).group(0)
        memory.update_user_profile(age=age)
        saved = True
    if any(w in content for w in Keywords.SIBLING_HINTS):
        memory.update_user_profile(sibling=content)
        saved = True

    # 统一写入记忆点（供语义检索命中）；个人信息同样入库
    memory.save_memory_point(content, source=source)
    if saved:
        console.action("记忆 用户资料已更新")
    else:
        console.action(f"记忆 已保存：{content[:30]}")


def backfill_name_from_profile():
    """
    启动回填（问题3）：user_profile 无名字时，从已有记忆点解析用户名字。
    修复"第2次启动打招呼仍叫不出名字"：名字进了记忆点但没同步到 user_profile。
    """
    try:
        profile = memory.get_user_profile()
        if profile.get("name"):
            return
        for mp in memory.get_all_memory_points():
            name = _parse_name(mp["content"])
            if name:
                memory.update_user_profile(name=name)
                console.action(f"记忆 回填用户名：{name}")
                return
    except Exception as e:
        console.error(f"名字回填失败：{e}")


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
        if m: memory.save_memory_point(m.group(1).strip(), source="summary")
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