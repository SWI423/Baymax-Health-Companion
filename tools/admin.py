"""
大白数据库诊断工具 - 查看 6 张表的真实状态。
用于测试时验证数据是否真的存进去了。
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import memory


def _line(char="=", length=60):
    print(char * length)


def show_user_profile():
    _line()
    print("【表1：user_profile 用户信息】")
    _line("-")
    profile = memory.get_user_profile()
    if not profile or not any(profile.get(k) for k in ["name", "age", "birthday", "sibling"]):
        print("  （空）")
        return
    for key, label in [("user_id", "用户ID"), ("name", "名字"),
                        ("age", "年龄"), ("birthday", "生日"),
                        ("health_id", "健康编号"), ("sibling", "兄弟姐妹")]:
        if profile.get(key):
            print(f"  {label}: {profile[key]}")


def show_memory_points():
    _line()
    print("【表2：memory_points 记忆点】")
    _line("-")
    points = memory.get_all_memory_points()
    if not points:
        print("  （空）")
        return
    for p in points:
        print(f"  [{p['id']}] (来源:{p['source']} 重要性:{p['importance']})")
        print(f"      {p['content']}")


def show_chat_short():
    _line()
    print("【表3：chat_short 短期对话】")
    _line("-")
    chats = memory.get_recent_chats(limit=20)
    if not chats:
        print("  （空）")
        return
    for i, c in enumerate(chats, 1):
        role = "用户" if c["role"] == "user" else "大白"
        content = c["content"][:60].replace("\n", " ")
        if len(c["content"]) > 60:
            content += "..."
        print(f"  {i:02d}. {role}: {content}")


def show_chat_long():
    _line()
    print("【表4：chat_long 长期摘要】")
    _line("-")
    summaries = memory.get_recent_summaries(limit=10)
    if not summaries:
        print("  （空）")
        return
    for s in summaries:
        print(f"  [{s['period_start']} ~ {s['period_end']}]")
        print(f"    {s['summary']}")


def show_health_log():
    _line()
    print("【表5：health_log 健康记录】")
    _line("-")
    health = memory.get_recent_health_events(limit=10)
    if not health:
        print("  （空）")
        return
    for h in health:
        ts = h["timestamp"][:19] if h["timestamp"] else ""
        print(f"  [{ts}] {h['event_type']}: {h['detail']}")


def show_reminders():
    _line()
    print("【表6：reminders 定时提醒】")
    _line("-")
    reminders = memory.get_all_reminders()
    if not reminders:
        print("  （空）")
        return
    for r in reminders:
        status_cn = {"active": "启用中", "cancelled": "已取消",
                     "completed": "已完成"}.get(r["status"], r["status"])
        last = r["last_triggered"][:19] if r["last_triggered"] else "从未触发"
        print(f"  {r['event_name']}: {r['time']} | 频率:{r['frequency']} | "
              f"状态:{status_cn} | 上次触发:{last}")


def show_statistics():
    _line()
    print("【统计】")
    _line("-")
    print(f"  未总结对话数：{memory.count_unsummarized_chats()}")
    print(f"  记忆点总数：{len(memory.get_all_memory_points())}")
    print(f"  长期摘要总数：{len(memory.get_recent_summaries(limit=999))}")
    print(f"  健康记录总数：{len(memory.get_recent_health_events(limit=999))}")
    print(f"  提醒总数：{len(memory.get_all_reminders())}")


def show_all():
    print()
    _line()
    print("  大白数据库诊断报告")
    _line()
    show_user_profile()
    show_memory_points()
    show_chat_short()
    show_chat_long()
    show_health_log()
    show_reminders()
    show_statistics()
    _line()
    print()


if __name__ == "__main__":
    memory.init_db()
    show_all()