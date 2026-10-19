"""
大白 - 主入口
第一阶段：启动窗口，键盘控制表情。
"""
import pygame
import sys

from output.face import (
    init_face, get_screen, get_clock, update, draw,
    blink, look_half, hold_half, hold_closed, open_eyes
)


def main():
    init_face()

    screen = get_screen()
    clock = get_clock()

    running = True
    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:
                    blink(80.0, 1)
                    print("1 - 眨眼（快）")
                elif event.key == pygame.K_2:
                    hold_half(6.0)
                    print("2 - 持续眯眼（慢眯）")
                elif event.key == pygame.K_3:
                    look_half(15.0, hold=1.0)
                    print("3 - 眯一会（1秒）")
                elif event.key == pygame.K_4:
                    hold_closed(20.0)
                    print("4 - 闭眼")
                elif event.key == pygame.K_5:
                    blink(100.0, 2)
                    print("5 - 快眨眼 x2")
                elif event.key == pygame.K_6:
                    blink(15.0, 1)
                    print("6 - 慢眨眼")
                elif event.key == pygame.K_0:
                    open_eyes(15.0)
                    print("0 - 平滑恢复睁眼")

        update(dt)
        draw()
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()