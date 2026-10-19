import time
from enum import Enum
import sys
import os
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import brain

class State(Enum):
    SLEEP = "S1_休眠"
    GREET = "S2_问候"
    IDLE = "S3_待机"
    CHAT = "S4_聊天"
    CARE = "S5_关心"
    REMIND = "S6_提醒"
    URGE = "S7_催促"

class BaymaxFSM:
    def __init__(self):
        self.state = State.SLEEP
        self.state_enter_time = time.time()
        self.wake_reason = None
        self.current_emotion = "sleepy"
        self.pause_timeout = False
        self.emotion_hold_timer = 0.0 # 👈 记录情绪保持时间

    def set_emotion(self, emotion):
        self.current_emotion = emotion
        self.emotion_hold_timer = time.time() # 重置情绪计时器

    def change_state(self, new_state):
        if self.state == new_state: return
        old_state = self.state
        print(f"\n[FSM] 状态切换: {self.state.value} -> {new_state.value}")
        self.state = new_state
        self.state_enter_time = time.time()

        if self.state == State.SLEEP:
            self.set_emotion("sleepy")
        elif self.state == State.GREET:
            self.set_emotion("greet")
        elif self.state == State.IDLE:
            # 👈 从聊天回到待机时，不要立刻覆盖情绪，让子线程把情绪抛过来
            if old_state != State.CHAT:
                self.set_emotion("neutral")
        elif self.state == State.CHAT:
            pass
        elif self.state == State.CARE:
            self.set_emotion("concern")
        elif self.state == State.REMIND:
            self.set_emotion("alert")
        elif self.state == State.URGE:
            self.set_emotion("serious")

    def handle_event(self, event_type, payload=None):
        if self.state == State.SLEEP:
            if event_type in ["WAKE_USER", "WAKE_SENSOR", "WAKE_TIMER"]:
                self.wake_reason = event_type.split("_")[1].lower()
                self.change_state(State.GREET)
        elif self.state == State.GREET:
            if event_type == "GREET_FINISH":
                if self.wake_reason == "user": self.change_state(State.IDLE)
                elif self.wake_reason == "sensor": self.change_state(State.CARE)
                elif self.wake_reason == "timer": self.change_state(State.REMIND)
        elif self.state == State.IDLE:
            if event_type == "USER_INPUT":
                self.change_state(State.CHAT)
                self.handle_chat(payload)
            elif event_type == "SENSOR_ALERT": self.change_state(State.CARE)
            elif event_type == "TIMER_ALERT": self.change_state(State.REMIND)
            elif event_type == "TIMEOUT_IDLE": self.change_state(State.SLEEP)
        elif self.state == State.CHAT:
            if event_type == "USER_INPUT":
                if payload and "满意" in payload:
                    self.change_state(State.SLEEP)
                else:
                    self.handle_chat(payload)
            elif event_type == "SENSOR_ALERT": self.change_state(State.CARE)
            elif event_type == "TIMEOUT_CHAT": self.change_state(State.IDLE)
        elif self.state == State.CARE:
            if event_type == "USER_INPUT":
                self.change_state(State.CHAT)
                self.handle_chat(payload)
            elif event_type == "TIMEOUT_CARE": self.change_state(State.IDLE)
        elif self.state == State.REMIND:
            if event_type == "REMIND_CONFIRMED": self.change_state(State.IDLE)
            elif event_type == "TIMEOUT_REMIND": self.change_state(State.URGE)
        elif self.state == State.URGE:
            if event_type == "REMIND_CONFIRMED": self.change_state(State.IDLE)
            elif event_type == "USER_INPUT":
                self.handle_chat(payload)
                self.change_state(State.IDLE)
            elif event_type == "TIMEOUT_URGE": self.change_state(State.IDLE)

    def handle_chat(self, user_text):
        if not user_text: return
        # 👈 输入即刻预判：调用大模型之前，先按关键词把表情切到 concern
        quick_emotion = brain.predict_emotion_quick(user_text)
        if quick_emotion:
            print(f"🎭 [即时预判] 关键词命中，表情提前切换: {quick_emotion}")
            self.set_emotion(quick_emotion)
        def _chat_worker():
            print("\n大白：", end="", flush=True)
            result = brain.ask_baymax(user_text, wait_pass2=True, on_chunk=lambda c: print(c, end="", flush=True))
            print()
            # 👈 异步精准覆盖：Pass 2 算出的真实情绪，立即覆盖之前的预判
            final_emotion = result.get("emotion")
            if final_emotion:
                print(f"🎭 [精准覆盖] 应用 Pass 2 情绪: {final_emotion}")
                self.set_emotion(final_emotion)
            self.state_enter_time = 0 # 触发超时，回到待机
        threading.Thread(target=_chat_worker, daemon=True).start()

    def update(self):
        if self.pause_timeout:
            self.state_enter_time = time.time()
            return

        now = time.time()
        elapsed = now - self.state_enter_time

        # 👈 核心逻辑：如果情绪保持了 3 秒以上，且当前处于待机状态，强制恢复 neutral
        if self.state == State.IDLE:
            if now - self.emotion_hold_timer > 3.0 and self.current_emotion != "neutral":
                print("⏳ [FSM] 情绪保持结束，恢复平静待机。")
                self.set_emotion("neutral")
            elif elapsed > 60:
                self.handle_event("TIMEOUT_IDLE")

        elif self.state == State.GREET and elapsed > 3.0:
            self.handle_event("GREET_FINISH")
        elif self.state == State.CHAT and elapsed > 120:
            self.handle_event("TIMEOUT_CHAT")
        elif self.state == State.CARE and elapsed > 15:
            self.handle_event("TIMEOUT_CARE")