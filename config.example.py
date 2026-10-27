"""
大白项目 - 配置示例（提交到 GitHub 用）
用法：复制本文件为 config.py，填入你自己的智谱 API Key 即可运行。
⚠️ config.py 含密钥，已被 .gitignore 忽略，绝不提交。
"""
import os
from datetime import datetime

# ================= 路径配置 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMES_PATH = os.path.join(BASE_DIR, "assets", "frames")
DATABASE_PATH = os.path.join(BASE_DIR, "data", "baymax_memory.db")
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

# ================= API 配置 =================
# 👉 填入你的智谱开放平台 Key：https://open.bigmodel.cn/
API_KEY = "YOUR_ZHIPU_API_KEY_HERE"
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL_NAME = "glm-4-flash"

# ================= 输出语言 =================
# 可选："中文" / "English" / "日本語" / "自动"（跟随用户输入）
LANGUAGE = "中文"


# ================= 表情即时预判关键词 =================
# 用户输入命中这些词时，在调用大模型之前立即切换为 concern（担忧半眯眼），
# 随后 brain.py Pass 2 提取到的精准情绪会覆盖此预判。
QUICK_CONCERN_KEYWORDS = ["难过", "痛", "累", "不舒服", "难受",
                          "伤心", "委屈", "害怕", "担心", "想哭"]

# 命中这些词时，立即切换为 serious（沉重半眯眼）：
# 熬夜/不睡/必须 等表达"硬撑/坚持"的语境，大白先严肃起来再说话。
QUICK_SERIOUS_KEYWORDS = ["熬夜", "不睡", "通宵", "必须", "坚持", "硬撑", "死磕"]


# ============================================================
# 固定话术（代码级模板，不走大模型）
# 设计原则：固定指令 → 固定回应用代码保证 100% 稳定；自由对话才交给 LLM
# ============================================================

# ---- 唤醒招呼 ----
# 模板：{称呼}，{时段问候}，我叫大白，是你的私人健康助理。
GREETING_TEMPLATE = "{who}，{greet}，我叫大白，是你的私人健康助理。"
# 没记录用户名字时的称呼
UNKNOWN_NAME_GREETING = "您好"


def build_greeting(name=None):
    """按当前时段生成唤醒招呼语（称呼 + 时段问候 + 自我介绍）"""
    hour = datetime.now().hour
    if 5 <= hour < 11:
        greet = "早上好"
    elif 11 <= hour < 13:
        greet = "中午好"
    elif 13 <= hour < 18:
        greet = "下午好"
    elif 18 <= hour < 23:
        greet = "晚上好"
    else:
        greet = "夜深了"
    who = name if name else UNKNOWN_NAME_GREETING
    return GREETING_TEMPLATE.format(who=who, greet=greet)


# ---- 固定指令 → 固定回应 ----
FAREWELL_TRIGGER = "满意"  # 说"满意"即结束服务（全局入口检测）
FAREWELL_REPLY = "很高兴帮到你，我会一直在，直到你需要帮助。"

# ---- 提醒 / 催促 / 理由考察 场景固定回应（简单纯粹，不讨好）----
COMPLETE_REPLY = "好的。"  # 用户确认完成（不夸赞，稳住形象）
ACCEPT_REASON_REPLY = "好，那这次就不勉强你了。"  # 理由充分 → 允许不完成
REJECT_REASON_REPLY = "我知道你有理由，但这件事还是值得做完，我陪你一起。"  # 理由不行 → 开导
REMIND_REPLY = "⏰ {event_name}的时间到啦，先把手头的事放一放。"
URGE_REPLY = "……完成了吗？跟我说一声，我才能放心。"

# ---- 传感异常关怀开场（S5 关心状态主动询问，大白是健康助理不是被动表情）----
CARE_OPENERS = {
    "fall": "我检测到你摔倒了。先别急着动，深呼吸，我陪着你。告诉我你现在哪里不舒服。",
    "heart": "我检测到你心率偏高了。先坐下来，慢慢呼气，我来帮你看一下情况。你现在感觉怎么样？",
}


# ============================================================
# 相对日期关键词（用户口头设定一次性提醒时，代码层换算具体日期）
# ============================================================
RELATIVE_DATE_PATTERN = r"今天|明天|后天|大后天|下(?:个)?(?:星期|周)(?:一|二|三|四|五|六|日|天)|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}"


# ================= 关键词与正则 =================
class Keywords:
    """集中管理所有关键词和占位符，方便扩充"""

    # 记忆分表触发词
    NAME_HINTS = ["名字", "我叫", "称呼", "大名"]
    AGE_HINTS = ["岁", "年龄", "虚岁"]
    BIRTHDAY_HINTS = ["生日", "出生"]
    SIBLING_HINTS = ["弟弟", "妹妹", "哥哥", "姐姐", "爸", "妈"]

    # 时间修饰词 → 小时偏移
    PERIOD_MAP = {
        "早上": 0, "上午": 0, "凌晨": 0,
        "中午": 0,
        "下午": 12, "晚上": 12, "今晚": 12, "明晚": 12,
        "深夜": 12, "半夜": 12,
    }

    # 摘要占位符（避免大模型抄提示词模板）
    PLACEHOLDER_VALUES = {"值", "无", "未知", "没有", "不详",
                          "N/A", "未提及", "暂无", "不记得"}


# ================= 视觉参数 =================
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 800
FACE_SIZE = 400

FRAME_OPEN = 0
FRAME_HALF = 5
FRAME_CLOSED = 10
MAX_FRAME = 20
TOTAL_FRAMES = 21


# ============================================================
# 设置页白名单（桌宠 ⚙️ 可编辑区）
# 原则：只能改"简单人设补充"，核心提示词（人设全量 SYSTEM_PROMPT /
#      Pass2 动作提取 / 工具说明书 TOOLS）硬编码在 prompts.py / brain.py，
#      设置页无任何 UI 入口。
# ============================================================
USER_TWEAKABLE_PROMPTS_DEFAULTS = {
    "性格补充": "沉稳、体贴、诙谐，一本正经的冷面笑匠；简洁回应，不说废话，危机时极认真。",
    "陪伴风格": "像电影里的大白：温柔、平静、缓慢；记住用户说过的，结合健康数据给出正确护理信息。",
}
# 用户修改持久化到 data/user_prompts.json（保存/启动自动读写）
USER_PROMPTS_FILE = os.path.join(BASE_DIR, "data", "user_prompts.json")
