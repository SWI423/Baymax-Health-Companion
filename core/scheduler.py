# scheduler.py —— 定时提醒调度器（第二阶段核心：定时健康督促）
"""
后台线程轮询 reminders 表：到点且当天该分钟未触发 → 回调外部函数唤醒大白。

用法（在 main.py 中）：
    def _on_reminder_due(reminder):
        event = "WAKE_TIMER" if fsm.state == State.SLEEP else "TIMER_ALERT"
        fsm.handle_event(event)

    scheduler = ReminderScheduler(on_due=_on_reminder_due)
    scheduler.start()
"""
import threading
import time

from core import memory

POLL_INTERVAL = 5  # 轮询间隔（秒）


class ReminderScheduler:
    """到点提醒调度器：on_due(reminder) 由外部注入，避免与状态机循环依赖"""

    def __init__(self, on_due=None):
        self._on_due = on_due
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[scheduler] 定时提醒调度器已启动")

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._check()
            except Exception as e:  # 单次检查失败不拖垮整个调度线程
                print(f"[scheduler] 检查提醒出错：{e}")
            time.sleep(POLL_INTERVAL)

    def _check(self):
        now = time.localtime()
        hhmm = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        today = f"{now.tm_year}-{now.tm_mon:02d}-{now.tm_mday:02d}"
        date_prefix = today

        for r in memory.get_all_reminders(only_active=True):
            if r["time"] != hhmm:
                continue
            rdate = r.get("date") or ""
            # 一次性提醒：指定了具体日期且不是今天 → 跳过
            if rdate and rdate != today:
                continue
            # 当日同分钟已触发过 → 跳过（避免轮询周期内重复唤醒）
            last = r.get("last_triggered") or ""
            if last.startswith(date_prefix) and last[11:16] == hhmm:
                continue
            # 一次性提醒触发后停用（保留历史），每日提醒只记触发时间
            if r.get("frequency") == "once":
                memory.complete_reminder(r["event_name"])
            else:
                memory.mark_reminder_triggered(r["event_name"])
            print(f"[scheduler] 到点提醒：{r['event_name']}（{r['time']}，{'一次性' if rdate else '每日'}）")
            if self._on_due:
                self._on_due(r)
