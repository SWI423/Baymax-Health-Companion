import time
from enum import Enum
import sys
import os
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import console
from core import brain
from core import memory
from config import (COMPLETE_REPLY, ACCEPT_REASON_REPLY, REJECT_REASON_REPLY,
                    FAREWELL_REPLY, FAREWELL_TRIGGER, CARE_OPENERS)

class State(Enum):
    SLEEP = "S1_休眠"
    GREET = "S2_问候"
    IDLE = "S3_待机"
    CHAT = "S4_聊天"
    CARE = "S5_关心"
    REMIND = "S6_提醒"
    URGE = "S7_催促"

class BaymaxFSM:
    def __init__(self, on_output=None, on_bot_start=None, on_chunk=None, on_chat_done=None):
        """输出通道抽象：默认=命令行 print；桌宠版注入 UI 回调（行为不变）
        on_output(text)    : 完整口播一句（招呼/提醒/告别/完成等）
        on_bot_start()     : 流式说话开始（输出前缀）
        on_chunk(chunk)    : 流式 token
        on_chat_done(reply, emotion) : 聊天回合结束
        """
        self.state = State.SLEEP
        self.state_enter_time = time.time()
        self.wake_reason = None
        self.current_emotion = "sleepy"
        self.pause_timeout = False
        self.emotion_hold_timer = 0.0 # 👈 记录情绪保持时间
        self.pending_reminder = None   # 👈 待确认提醒上下文（提醒口播后进聊天，输入先走三出口）
        self._sensor_kind = None       # 👈 传感类型：fall摔倒 / heart心率偏高
        self._output = on_output or (lambda t: print(f"\n(●––●): {t}") if t else None)
        self._on_bot_start = on_bot_start or (lambda: print("\n(●––●): ", end="", flush=True))
        self._on_chunk = on_chunk or (lambda c: print(c, end="", flush=True))
        self._on_chat_done = on_chat_done or (lambda reply, emotion: None)

    def set_emotion(self, emotion):
        self.current_emotion = emotion
        self.emotion_hold_timer = time.time() # 重置情绪计时器

    @staticmethod
    def _parse_sensor_kind(payload):
        """传感类型解析：payload 可为 {"kind":"fall"} / {"kind":"heart"} / 纯字符串"""
        if isinstance(payload, dict):
            return payload.get("kind", "fall")
        return "fall"

    def change_state(self, new_state):
        if self.state == new_state: return
        old_state = self.state
        console.debug(f"状态切换: {self.state.value} -> {new_state.value}")
        self.state = new_state
        self.state_enter_time = time.time()

        if self.state == State.SLEEP:
            self.set_emotion("sleepy")
        elif self.state == State.GREET:
            self.set_emotion("greet")
        elif self.state == State.IDLE:
            # 👈 从聊天/关心回到待机时，不要立刻覆盖情绪，让子线程把情绪抛过来
            #    （文档：突发关心结束也要保留半眯眼 3 秒，由 update() 计时后恢复 neutral）
            if old_state not in (State.CHAT, State.CARE):
                self.set_emotion("neutral")
        elif self.state == State.CHAT:
            pass
        elif self.state == State.CARE:
            self.set_emotion("concern")
            self._start_care_flow()   # 👈 传感关怀主流程：主动询问 + 大模型建议
        elif self.state == State.REMIND:
            self.set_emotion("alert")
        elif self.state == State.URGE:
            self.set_emotion("serious")

    def handle_event(self, event_type, payload=None):
        # 👈 结束服务信号（全局入口）：任意可对话状态说"满意" → 告别并休眠。
        #    放在这里而不是只在 CHAT 分支：用户在待机/关心/催促时直接说
        #    "我很满意你的服务"也能正确结束，避免走普通聊天路径。
        if event_type == "USER_INPUT" and payload and FAREWELL_TRIGGER in str(payload):
            if self.state in (State.IDLE, State.CHAT, State.CARE, State.URGE):
                self._finish_service_and_sleep(payload)
                return

        if self.state == State.SLEEP:
            if event_type in ["WAKE_USER", "WAKE_SENSOR", "WAKE_TIMER"]:
                self.wake_reason = event_type.split("_")[1].lower()
                if self.wake_reason == "timer":
                    self.pending_reminder = payload  # 定时唤醒：携带提醒上下文
                elif self.wake_reason == "sensor":
                    self._sensor_kind = self._parse_sensor_kind(payload)
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
            elif event_type == "SENSOR_ALERT":
                self._sensor_kind = self._parse_sensor_kind(payload)
                self.change_state(State.CARE)
            elif event_type == "TIMER_ALERT":
                self.pending_reminder = payload  # 提醒在身：携带上下文进提醒状态
                self.change_state(State.REMIND)
            elif event_type == "TIMEOUT_IDLE": self.change_state(State.SLEEP)
        elif self.state == State.CHAT:
            if event_type == "USER_INPUT":
                # 提醒在身：输入先走三出口（完成/理由考察/闲聊）；无提醒走普通聊天
                if self.pending_reminder:
                    self._handle_reminder_reply(payload)
                else:
                    self.handle_chat(payload)
            elif event_type == "SENSOR_ALERT":
                self._sensor_kind = self._parse_sensor_kind(payload)
                self.change_state(State.CARE)
            elif event_type == "TIMEOUT_CHAT": self.change_state(State.IDLE)
        elif self.state == State.CARE:
            if event_type == "USER_INPUT":
                self.change_state(State.CHAT)
                self.handle_chat(payload)
            elif event_type == "CARE_FLOW_DONE":
                # 关怀建议说完 → 转聊天等用户回答，继续关怀对话
                self.change_state(State.CHAT)
            elif event_type == "TIMEOUT_CARE": self.change_state(State.IDLE)
        elif self.state == State.REMIND:
            # 👈 状态图 S6：E10 确认完成 → 结束；E11 给理由 → 大模型判断（聊天语境）；
            #    E5 满意 → 休眠（全局入口已处理）；口播完成 3 秒后自动进聊天（update）
            if event_type == "USER_INPUT":
                self._handle_reminder_reply(payload)
            elif event_type == "REMIND_CONFIRMED":
                self.pending_reminder = None
                self.change_state(State.IDLE)
        elif self.state == State.URGE:
            # 👈 状态图 S7：E11 用户给理由 → 大模型判断（接受→结束/拒绝→继续催）；
            #    E9 用户沉默15秒 → 回待机；E5 满意 → 休眠
            if event_type == "USER_INPUT":
                self._handle_reminder_reply(payload)
            elif event_type == "REMIND_CONFIRMED":
                self.pending_reminder = None
                self.change_state(State.IDLE)
            elif event_type == "TIMEOUT_URGE":
                self.pending_reminder = None  # 放弃本次提醒
                self.change_state(State.IDLE)

    def _start_care_flow(self):
        """S5 关心状态核心：传感异常时大白主动开口（固定开场），
        随后后台走 Agent 路径（结合记忆/RAG/工具）生成完整询问+建议，
        完成后经 action_queue 投递 CARE_FLOW_DONE，主循环转聊天等用户回答。"""
        kind = self._sensor_kind or "fall"
        console.action(f"传感关怀 {kind}")
        opener = CARE_OPENERS.get(kind, CARE_OPENERS["fall"])
        self._output(opener)

        def worker():
            try:
                self._on_bot_start()
                result = brain.ask_care_advice(kind, on_chunk=self._on_chunk)
                brain.queue_action({"type": "CARE_FLOW_DONE", "reply": result.get("reply", "")})
            except Exception as e:
                console.error(f"关怀流程失败：{e}")
                brain.queue_action({"type": "CARE_FLOW_DONE", "reply": ""})

        threading.Thread(target=worker, daemon=True).start()

    def handle_chat(self, user_text):
        if not user_text: return
        # 👈 输入即刻预判：调用大模型之前，先按关键词把表情切到 concern/serious
        quick_emotion = brain.predict_emotion_quick(user_text)
        if quick_emotion:
            console.emotion(f"即时预判 → {quick_emotion}（关键词命中）")
            self.set_emotion(quick_emotion)
        def _chat_worker():
            # Agent 化主入口：模型自主决策调用工具（记忆/定时/知识库），再出人话
            self._on_bot_start()
            result = brain.ask_baymax_with_tools(user_text, wait_pass2=True, on_chunk=self._on_chunk)
            # 👈 异步精准覆盖：Pass 2 算出的真实情绪，立即覆盖之前的预判
            final_emotion = result.get("emotion")
            if final_emotion:
                console.emotion(f"精准覆盖 → {final_emotion}")
                self.set_emotion(final_emotion)
            self.state_enter_time = 0 # 触发超时，回到待机
            self._on_chat_done(result.get("reply", ""), final_emotion or "")
        threading.Thread(target=_chat_worker, daemon=True).start()

    def _finish_service_and_sleep(self, payload):
        """用户说'满意'结束服务：大白告别 → 进入休眠（不调大模型，告别语为固定人设台词）"""
        console.action("服务 结束并休眠")
        farewell = FAREWELL_REPLY
        self._output(farewell)
        # 保留一段完整对话记录（用户最后一句 + 告别语）
        memory.save_chat("user", str(payload).strip())
        memory.save_chat("assistant", farewell)
        self.pending_reminder = None  # 服务结束，丢弃待确认提醒上下文
        self.change_state(State.SLEEP)

    def _handle_reminder_reply(self, user_text):
        """
        提醒/催促场景的用户回应三出口（状态图 S6/S7，问题2：在聊天语境执行）：
          - completed      → 淡淡一句"好的"结束提醒（不夸赞，稳住形象）→ 回待机
          - not_completed  → 异步交给大模型考察理由：
                              accept → 允许不完成（回待机）；reject → 催促+开导（S7）
          - None（闲聊）   → 走大模型正常对话，聊完仍在聊天语境（提醒主题不丢）
        理由考察结果经 action_queue 投递，由主循环统一执行状态切换（线程安全）。
        """
        quick = brain.predict_completion_quick(user_text)
        if quick == "completed":
            self._output(COMPLETE_REPLY)
            self.pending_reminder = None
            self.change_state(State.IDLE)
        elif quick == "not_completed":
            def _judge_worker():
                verdict = brain.judge_reason(user_text)
                console.debug(f"理由考察结果：{verdict}（回应：{str(user_text)[:20]}…）")
                brain.queue_action({"type": "REMINDER_REASON", "verdict": verdict})

            threading.Thread(target=_judge_worker, daemon=True).start()
        else:
            # 闲聊/不确定：正常对话（提醒仍在身，沉默5分钟会重复提醒）
            self.handle_chat(user_text)

    def update(self):
        if self.pause_timeout:
            self.state_enter_time = time.time()
            return

        now = time.time()
        elapsed = now - self.state_enter_time

        # 👈 核心逻辑：如果情绪保持了 3 秒以上，且当前处于待机状态，强制恢复 neutral
        if self.state == State.IDLE:
            if now - self.emotion_hold_timer > 3.0 and self.current_emotion != "neutral":
                console.debug("情绪保持结束，恢复平静待机")
                self.set_emotion("neutral")
            elif elapsed > 60:
                self.handle_event("TIMEOUT_IDLE")

        elif self.state == State.GREET and elapsed > 3.0:
            self.handle_event("GREET_FINISH")
        elif self.state == State.CHAT:
            if self.pending_reminder and elapsed > 300:
                # 👈 提醒在身 + 沉默 5 分钟 → 重复提醒（重新口播+重新计时），留在聊天语境
                console.debug("提醒 5 分钟无回应，重复提醒")
                self.state_enter_time = time.time()
                brain.queue_action({"type": "REPEAT_REMIND"})
            elif not self.pending_reminder and elapsed > 120:
                self.handle_event("TIMEOUT_CHAT")
        elif self.state == State.CARE and elapsed > 15:
            self.handle_event("TIMEOUT_CARE")
        elif self.state == State.REMIND and elapsed > 3:
            # 👈 提醒口播完成（约 3 秒）→ 自动进聊天状态等用户回应（问题2：
            #    提醒完后进入聊天，输入在聊天语境走完成/理由判定路线）
            console.debug("提醒口播完成，进入聊天等待回应")
            self.change_state(State.CHAT)
        elif self.state == State.URGE and elapsed > 15:
            # 👈 状态图 E9：用户沉默 15 秒 → 回待机（不再继续打扰），放弃本次提醒
            console.debug("催促沉默 15 秒，退回待机")
            self.handle_event("TIMEOUT_URGE")