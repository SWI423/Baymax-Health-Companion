import pygame
import sys
import os
import threading

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import WINDOW_WIDTH, WINDOW_HEIGHT
from output import face
from core.state_machine import BaymaxFSM, State
from core import brain

fsm = BaymaxFSM()

def get_user_input_console():
    print("\n" + "=" * 40)
    print("👉 [大白已准备好倾听，请慢慢打字，回车发送]")
    text = input("你：")
    if text:
        fsm.handle_event("USER_INPUT", payload=text)
    print("=" * 40 + "\n")
    fsm.pause_timeout = False

def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("大白 Baymax - 第一阶段")

    face.init_face()
    clock = pygame.time.Clock()
    fsm.change_state(State.SLEEP)

    running = True
    while running:
        dt = clock.tick(60) / 1000.0

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

        pending_emotion = brain.get_pending_emotion()
        if pending_emotion:
            print(f"🎭 [主循环] 捕获到后台情绪: {pending_emotion}")
            # 👈 如果状态机此时已经回到待机，立刻更新情绪并重置计时
            fsm.set_emotion(pending_emotion)

        fsm.update()

        face.set_emotion(fsm.current_emotion)
        face.update(dt)
        face.draw()

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()