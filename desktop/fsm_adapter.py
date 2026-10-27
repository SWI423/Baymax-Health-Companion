# -*- coding: utf-8 -*-
"""FSM 适配器：把命令行版状态机完整迁移到桌宠
- QTimer 100ms 驱动 fsm.update()（状态超时/情绪保持/提醒自动进聊天）
- 状态进入事件 → 口播（招呼/提醒/催促/告别）到聊天页 + 提醒气泡
- LLM 异步情绪 get_pending_emotion → fsm.set_emotion → 表情
- action_queue 消费（理由考察 accept/reject / 重复提醒）
- 唤醒映射：点击脸(WAKE_USER) / 提醒到点(WAKE_TIMER/TIMER_ALERT) / 键盘 F 传感模拟
- SLEEP 时直接聊天 → 先唤醒，GREET 结束后自动投递输入
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from core import brain, memory, console
from core.state_machine import BaymaxFSM, State
from config import (
    build_greeting, REMIND_REPLY, URGE_REPLY,
    ACCEPT_REASON_REPLY, REJECT_REASON_REPLY,
)

TICK_MS = 100


class FsmAdapter(QObject):
    """FSM 适配器（主线程 QTimer 驱动）
    线程安全规则：LLM/Pass2/调度器/摘要等都在子线程，任何 UI 输出一律通过
    pyqtSignal 跨线程投递 → 槽在主线程执行，绝不子线程直接碰 Qt 控件。
    """
    _sig_line = pyqtSignal(str)          # 完整一行口播
    _sig_bot_start = pyqtSignal()        # 流式开始
    _sig_chunk = pyqtSignal(str)         # 流式 token
    _sig_chat_done = pyqtSignal(str, str)  # (reply, emotion) 回合结束
    _sig_reminder = pyqtSignal(dict)     # 定时提醒到点（scheduler 线程 → 主线程处理）

    def __init__(self, pet, panel, bubble, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.panel = panel
        self.bubble = bubble
        self._current_reminder = None
        self._pending_input = None
        self._last_emotion = None
        self._last_state = None
        self._mem_snapshot = self._count_memory()
        self._rmd_snapshot = self._count_reminders()

        # 信号 → 主线程槽（子线程只 emit，Qt 自动排队）
        self._sig_line.connect(self._ui_show_line)
        self._sig_bot_start.connect(self._ui_bot_start)
        self._sig_chunk.connect(self._ui_chunk)
        self._sig_chat_done.connect(self._ui_chat_done)
        self._sig_reminder.connect(self._handle_reminder_due)

        # 输出通道：状态机 → 信号（任何线程调用都安全）
        self.fsm = BaymaxFSM(
            on_output=self._sig_line.emit,
            on_bot_start=self._sig_bot_start.emit,
            on_chunk=self._sig_chunk.emit,
            on_chat_done=self._sig_chat_done.emit,
        )

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(TICK_MS)

    # ---------- 状态区/输出（以下全部主线程执行） ----------
    def _ensure_panel(self):
        """大白说话 → 面板自动弹出（未显示时按大头四边选位置）并切到聊天页"""
        if not self.panel.isVisible():
            self.panel.show_near(self.pet.frameGeometry())
        if self.panel.pages.currentIndex() != 0:
            self.panel.nav.setCurrentRow(0)
            self.panel.pages.setCurrentIndex(0)

    def _ui_show_line(self, text):
        if text:
            self._ensure_panel()
            self.panel.chat_page.append_bot_line(text)

    def _ui_bot_start(self):
        self._ensure_panel()
        self.panel.chat_page.append_bot_start()

    def _ui_chunk(self, chunk):
        if chunk:
            self._ensure_panel()
        self.panel.chat_page.append_bot_chunk(chunk)

    def _ui_chat_done(self, reply, emotion):
        self.panel.chat_page.finish_round(reply, emotion)
        self._sync_status_after_chat()

    @staticmethod
    def _count_memory():
        try:
            return len(memory.get_all_memory_points())
        except Exception:
            return 0

    @staticmethod
    def _count_reminders():
        try:
            return len([r for r in memory.get_all_reminders(only_active=True)])
        except Exception:
            return 0

    def _sync_status_after_chat(self):
        mem_now, rmd_now = self._count_memory(), self._count_reminders()
        parts = []
        if mem_now != self._mem_snapshot:
            parts.append(f"记忆+{mem_now - self._mem_snapshot}")
            self._mem_snapshot = mem_now
        if rmd_now != self._rmd_snapshot:
            parts.append(f"提醒+{rmd_now - self._rmd_snapshot}")
            self._rmd_snapshot = rmd_now
        self.panel.set_status(action=" / ".join(parts) if parts else "—")
        self.panel.memory_page.refresh()
        self.panel.reminder_page.refresh()

    # ---------- 输入 / 唤醒 ----------
    def user_input(self, text):
        text = (text or "").strip()
        if not text:
            return
        if self.fsm.state == State.SLEEP:
            # 直接聊天 = 先唤醒，GREET 结束后自动投递本句（UI 显示由 ChatPage 负责）
            self.fsm.handle_event("WAKE_USER")
            self._pending_input = text
        else:
            self.fsm.handle_event("USER_INPUT", payload=text)

    def wake(self):
        if self.fsm.state == State.SLEEP:
            self.fsm.handle_event("WAKE_USER")

    def reminder_due(self, reminder):
        """scheduler 线程 → 只 emit 信号，由主线程统一处理（状态机只在主线程被操作）"""
        self._sig_reminder.emit(reminder)

    def _handle_reminder_due(self, reminder):
        """主线程：定时提醒触发 → 状态机事件（唤醒/提醒）"""
        self._current_reminder = reminder
        event = "WAKE_TIMER" if self.fsm.state == State.SLEEP else "TIMER_ALERT"
        console.action(f"定时提醒 触发：{reminder['event_name']}")
        self.fsm.handle_event(event, payload=reminder)

    # ---------- 主循环 ----------
    def tick(self):
        # 1) LLM 异步情绪
        pe = brain.get_pending_emotion()
        if pe:
            self.fsm.set_emotion(pe)

        # 2) 动作队列（理由考察结果/重复提醒）
        self._consume_action_queues()

        # 3) 状态机推进
        self.fsm.update()

        # 4) 状态进入事件（口播）
        st = self.fsm.state
        if st != self._last_state:
            self._on_state_entered(st)
            self._last_state = st

        # 5) 状态/情绪 → UI
        self.panel.set_status(state=st.value)
        if self.fsm.current_emotion != self._last_emotion:
            self._last_emotion = self.fsm.current_emotion
            self.pet.set_emotion(self.fsm.current_emotion)
            self.panel.set_status(emotion=self.fsm.current_emotion)

        # 6) 记忆命中显示
        n, score = memory.last_memory_hits[0]
        if n:
            self.panel.set_status(memory=f"{n} 最高{score:.2f}")

    def _consume_action_queues(self):
        while not brain.action_queue.empty():
            act = brain.action_queue.get_nowait()
            atype = act.get("type")
            if atype == "REMINDER_REASON":
                if not self.fsm.pending_reminder:
                    console.debug("理由考察结果到达时提醒上下文已结束，丢弃")
                    continue
                if act.get("verdict") == "accept":
                    self._ui_show_line(ACCEPT_REASON_REPLY)
                    self.fsm.handle_event("REMIND_CONFIRMED")  # → 回待机
                else:
                    self._ui_show_line(REJECT_REASON_REPLY)
                    self.fsm.change_state(State.URGE)          # → 催促+开导
            elif atype == "REPEAT_REMIND":
                if self._current_reminder:
                    self._say_reminder(self._current_reminder)
            elif atype == "CARE_FLOW_DONE":
                # 关怀建议说完 → 转聊天等用户回答（继续关怀对话）
                if self.fsm.state == State.CARE:
                    self.fsm.handle_event("CARE_FLOW_DONE")

    def _on_state_entered(self, st):
        if st == State.GREET:
            profile = memory.get_user_profile()
            self._ui_show_line(build_greeting(profile.get("name") or None))
        elif st == State.REMIND and self._current_reminder:
            self._say_reminder(self._current_reminder)
        elif st == State.URGE:
            self._ui_show_line(URGE_REPLY)
        elif st == State.SLEEP:
            self.panel.chat_page.release_input()   # 恢复输入（告别后休眠）
            self._summarize_in_background()
        elif st == State.IDLE:
            # 唤醒后排队的第一句输入，自动投递
            if self._pending_input:
                text, self._pending_input = self._pending_input, None
                self.fsm.handle_event("USER_INPUT", payload=text)

    def _say_reminder(self, reminder):
        text = REMIND_REPLY.format(event_name=reminder["event_name"])
        self._ui_show_line(text)
        self.bubble.show_reminder(text, self.pet.frameGeometry())

    def _summarize_in_background(self):
        def worker():
            try:
                brain.do_summary()
                console.action("休眠前摘要流程完成")
            except Exception as e:
                console.error(f"休眠前摘要失败：{e}")
        import threading
        threading.Thread(target=worker, daemon=True).start()
