import pygame
import sys
import os
import queue
import threading

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core import console
from config import (WINDOW_WIDTH, WINDOW_HEIGHT, build_greeting,
                    REMIND_REPLY, URGE_REPLY, ACCEPT_REASON_REPLY, REJECT_REASON_REPLY)
from output import face
from core.state_machine import BaymaxFSM, State
from core import brain
from core import memory
from core.scheduler import ReminderScheduler

fsm = BaymaxFSM()

# ============================================================
# 多线程同步：所有跨线程事件投递到队列，主循环统一消费。
# 状态机的一切状态/情绪变更只发生在主循环单线程内，天然无锁安全。
# ------------------------------------------------------------
#  event_queue  : 用户输入 / 定时器触发 → fsm.handle_event
#  brain.emotion_queue : LLM 异步情绪 → fsm.set_emotion（已有机制）
#  brain.action_queue  : LLM 异步动作（理由考察结果/重复提醒）→ 主循环执行
# ============================================================
event_queue = queue.Queue()


def post_event(event_type, payload=None):
    """线程安全地投递 FSM 事件（任意线程可调）"""
    event_queue.put((event_type, payload))


# 最近触发的提醒（供状态机进入 S6/S7 时让大白开口表达）
_current_reminder = None


def _on_reminder_due(reminder):
    """定时到点（scheduler 线程）：只投递事件（携带提醒上下文），由主循环统一处理"""
    global _current_reminder
    _current_reminder = reminder
    event = "WAKE_TIMER" if fsm.state == State.SLEEP else "TIMER_ALERT"
    console.action(f"定时提醒 触发：{reminder['event_name']}")
    post_event(event, payload=reminder)


scheduler = ReminderScheduler(on_due=_on_reminder_due)


def _say_reminder(reminder):
    """大白口吻说出提醒内容（进入 S6 提醒 / 5分钟重复提醒时调用）"""
    print(f"\n(●––●): {REMIND_REPLY.format(event_name=reminder['event_name'])}")


def _say_urge():
    """进入 S7 催促（理由被拒后）→ 大白开口追问"""
    print(f"\n(●––●): {URGE_REPLY}")


def _consume_action_queues():
    """主循环消费异步动作队列（理由考察结果 / 重复提醒）"""
    while not brain.action_queue.empty():
        act = brain.action_queue.get_nowait()
        atype = act.get("type")

        if atype == "REMINDER_REASON":
            # 只在提醒上下文中落地考察结果（期间用户再次回应则丢弃旧结果）
            if not fsm.pending_reminder:
                console.debug("理由考察结果到达时提醒上下文已结束，丢弃")
                continue
            if act.get("verdict") == "accept":
                print(f"\n(●––●): {ACCEPT_REASON_REPLY}")
                fsm.handle_event("REMIND_CONFIRMED")  # → 回待机（清上下文）
            else:
                print(f"\n(●––●): {REJECT_REASON_REPLY}")
                fsm.change_state(State.URGE)  # → 催促+开导（进入 URGE 会触发追问口播）

        elif atype == "REPEAT_REMIND":
            if _current_reminder:
                _say_reminder(_current_reminder)


def get_user_input_console():
    print("\n" + "─" * 46 + "\n💬 大白已准备好倾听，回车发送")
    text = input("你：")
    if text:
        post_event("USER_INPUT", payload=text)
    print("─" * 46)
    fsm.pause_timeout = False


def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("大白 Baymax - 第一阶段")

    face.init_face()
    clock = pygame.time.Clock()
    fsm.change_state(State.SLEEP)
    scheduler.start()
    brain.backfill_name_from_profile()  # 启动回填：没名字时从记忆点解析（问题3）

    running = True
    prev_state = State.SLEEP  # 启动即休眠，不触发首次摘要/招呼
    while running:
        dt = clock.tick(60) / 1000.0

        # ---- 键盘事件（主循环内，直接处理）----
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_w or event.key == pygame.K_1:
                    fsm.handle_event("WAKE_USER")
                elif event.key == pygame.K_f:
                    fsm.handle_event("WAKE_SENSOR" if fsm.state == State.SLEEP else "SENSOR_ALERT")
                elif event.key == pygame.K_h:
                    fsm.handle_event("WAKE_SENSOR" if fsm.state == State.SLEEP else "SENSOR_ALERT")
                elif event.key == pygame.K_t:
                    fsm.handle_event("WAKE_TIMER" if fsm.state == State.SLEEP else "TIMER_ALERT")
                elif event.key == pygame.K_SPACE:
                    if fsm.state not in [State.SLEEP, State.GREET]:
                        fsm.pause_timeout = True
                        threading.Thread(target=get_user_input_console, daemon=True).start()

        # ---- 消费跨线程事件（用户输入 / 定时器）----
        while not event_queue.empty():
            evt, payload = event_queue.get_nowait()
            fsm.handle_event(evt, payload=payload)

        # ---- 消费 LLM 异步情绪 ----
        pending_emotion = brain.get_pending_emotion()
        if pending_emotion:
            fsm.set_emotion(pending_emotion)

        fsm.update()

        # ---- 消费 LLM 异步动作（理由考察/重复提醒）----
        _consume_action_queues()

        # ---- 状态进入事件：口播 / 招呼 / 摘要 ----
        if fsm.state == State.GREET and prev_state != State.GREET:
            # 👈 唤醒招呼（config 模板：称呼+时段问候+自我介绍）
            profile = memory.get_user_profile()
            print(f"\n(●––●): {build_greeting(profile.get('name') or None)}")
        if fsm.state == State.REMIND and prev_state != State.REMIND and _current_reminder:
            _say_reminder(_current_reminder)
        if fsm.state == State.URGE and prev_state != State.URGE:
            _say_urge()
        if fsm.state == State.SLEEP and prev_state != State.SLEEP:
            threading.Thread(target=_summarize_in_background, daemon=True).start()
        prev_state = fsm.state

        face.set_emotion(fsm.current_emotion)
        face.update(dt)
        face.draw()

        pygame.display.flip()

    scheduler.stop()
    pygame.quit()
    sys.exit()


def _summarize_in_background():
    """进入休眠时，后台压缩未总结对话（三层摘要）"""
    try:
        brain.do_summary()
        console.action("休眠前摘要流程完成")
    except Exception as e:
        console.error(f"休眠前摘要失败：{e}")


if __name__ == "__main__":
    main()
