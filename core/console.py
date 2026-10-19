"""
统一终端输出层：收敛噪音、排版一致。

运行时只保留必要信息，一行一条：
    [RAG] 知识库命中 2 条 · 最高 0.73
    [记忆] 语义命中 1 条 · 最高 0.62
    [情绪] 即时预判 → concern
    [动作] 已记住：用户对青霉素过敏

排障细节（FSM 状态跳转、face 内部、启动横幅等）走 debug()，
需要时把 DEBUG 改成 True 即可，默认静音。
"""

DEBUG = False

# 各频道的固定标签，保证对齐
_TAGS = {
    "info":    "[信息]",
    "rag":     "[RAG]",
    "mem":     "[记忆]",
    "emotion": "[情绪]",
    "action":  "[动作]",
    "warn":    "[提醒]",
    "error":   "[错误]",
    "debug":   "[调试]",
}


def _emit(channel, msg):
    print(f"{_TAGS[channel]} {msg}", flush=True)


def info(msg):    _emit("info", msg)
def rag(msg):     _emit("rag", msg)
def mem(msg):     _emit("mem", msg)
def emotion(msg): _emit("emotion", msg)
def action(msg):  _emit("action", msg)
def warn(msg):    _emit("warn", msg)
def error(msg):   _emit("error", msg)


def debug(msg):
    if DEBUG:
        _emit("debug", msg)


def banner(title):
    """工具类脚本的标题横幅"""
    print()
    print("─" * 52)
    print(f"  {title}")
    print("─" * 52)
