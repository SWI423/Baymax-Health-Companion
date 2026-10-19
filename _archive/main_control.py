import pygame
import sys
import os

pygame.init()
screen = pygame.display.set_mode((800, 800))
pygame.display.set_caption("大白 Baymax - 眨眼控制台 v2")

# ================= 配置区 =================
base_path = r"/blink_frames"

# 关键帧位置
FRAME_OPEN = 0      # 睁眼
FRAME_HALF = 5      # 半眯眼
FRAME_CLOSED = 10   # 闭眼
MAX_FRAME = 20      # 序列最大帧号
# ==========================================

# 加载图片
frames = []
try:
    for i in range(0, 21):
        filename = f"{i:04d}.png"
        filepath = os.path.join(base_path, filename)
        img = pygame.image.load(filepath)
        w, h = img.get_size()
        scale = 400 / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = pygame.transform.scale(img, (new_w, new_h))
        frames.append(img)
    print(f"成功加载 {len(frames)} 张图片！")
except Exception as e:
    print(f"加载图片失败：{e}")
    sys.exit()

try:
    font = pygame.font.Font("C:/Windows/Fonts/msyh.ttc", 22)
except:
    font = pygame.font.Font(None, 22)

clock = pygame.time.Clock()

# ================= 状态机 =================
# 状态: idle / play / move_to / hold / return_to_open
current_frame = 0.0
mode = "idle"

# play 状态用
speed = 0.0
plays_remaining = 0

# move_to 状态用
target_frame = 0.0
move_speed = 0.0
next_mode_after_move = "idle"
hold_after_move = 0.0
hold_elapsed = 0.0

# return_to_open 状态用
return_speed = 0.0


def go_idle():
    global mode, current_frame
    mode = "idle"
    current_frame = 0.0


def play_blink(sp, count):
    """从0帧播到20帧（一次完整眨眼）"""
    global mode, current_frame, speed, plays_remaining
    mode = "play"
    current_frame = 0.0
    speed = sp
    plays_remaining = count


def move_to_frame(target, sp, after="idle", hold_dur=0.0):
    """平滑移动到目标帧，然后进入 after 状态"""
    global mode, target_frame, move_speed, next_mode_after_move
    global hold_after_move, hold_elapsed
    mode = "move_to"
    target_frame = float(target)
    move_speed = sp
    next_mode_after_move = after
    hold_after_move = hold_dur
    hold_elapsed = 0.0


def return_to_open(sp):
    """从当前帧平滑返回0帧（睁眼）"""
    global mode, return_speed
    mode = "return_to_open"
    return_speed = sp


# ================= 主循环 =================
running = True

while running:
    dt = clock.tick(60) / 1000.0

    # -------- 事件处理 --------
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_1:
                # (1) 眨眼 - 快速
                play_blink(80.0, 1)
                print("1 - 眨眼（快）")

            elif event.key == pygame.K_2:
                # (4) 持续眯眼 - 慢慢眯到第5帧，然后一直保持
                move_to_frame(FRAME_HALF, 6.0, after="hold", hold_dur=99999)
                print("2 - 持续眯眼（慢眯）")

            elif event.key == pygame.K_3:
                # (2) 眯一会 - 平滑眯到第5帧，保持1秒后自动返回
                move_to_frame(FRAME_HALF, 15.0, after="hold", hold_dur=1.0)
                print("3 - 眯一会（1秒）")

            elif event.key == pygame.K_4:
                # (2) 闭眼 - 平滑经过5帧到第10帧，然后一直保持
                move_to_frame(FRAME_CLOSED, 20.0, after="hold", hold_dur=99999)
                print("4 - 闭眼")

            elif event.key == pygame.K_5:
                # 快眨眼 - 连眨2次
                play_blink(100.0, 2)
                print("5 - 快眨眼 x2")

            elif event.key == pygame.K_6:
                # 慢眨眼
                play_blink(15.0, 1)
                print("6 - 慢眨眼")

            elif event.key == pygame.K_0:
                # (3) 平滑返回睁眼
                return_to_open(15.0)
                print("0 - 平滑恢复睁眼")

    # -------- 状态更新 --------
    if mode == "play":
        current_frame += speed * dt
        if current_frame >= MAX_FRAME:
            plays_remaining -= 1
            if plays_remaining > 0:
                current_frame = 0.0
            else:
                go_idle()

    elif mode == "move_to":
        # 平滑移动到目标帧
        if current_frame < target_frame:
            current_frame += move_speed * dt
            if current_frame >= target_frame:
                current_frame = target_frame
                mode = next_mode_after_move
                hold_elapsed = 0.0
        elif current_frame > target_frame:
            current_frame -= move_speed * dt
            if current_frame <= target_frame:
                current_frame = target_frame
                mode = next_mode_after_move
                hold_elapsed = 0.0
        else:
            mode = next_mode_after_move
            hold_elapsed = 0.0

    elif mode == "hold":
        hold_elapsed += dt
        if hold_elapsed >= hold_after_move:
            # 保持结束，平滑返回睁眼
            return_to_open(15.0)

    elif mode == "return_to_open":
        if current_frame > FRAME_OPEN:
            current_frame -= return_speed * dt
            if current_frame <= FRAME_OPEN:
                go_idle()
        else:
            go_idle()

    # -------- 绘制 --------
    screen.fill((240, 240, 245))
    idx = max(0, min(int(round(current_frame)), len(frames) - 1))
    rect = frames[idx].get_rect(center=(400, 400))
    screen.blit(frames[idx], rect)

    # 左上角状态
    status = font.render(f"帧: {idx:02d}  |  模式: {mode}", True, (50, 50, 50))
    screen.blit(status, (20, 20))

    # 左下角按键提示
    hints = [
        "1 - 眨眼（快）",
        "2 - 持续眯眼（慢眯）",
        "3 - 眯一会（1秒）",
        "4 - 闭眼",
        "5 - 快眨眼 x2",
        "6 - 慢眨眼",
        "0 - 平滑恢复睁眼",
    ]
    for i, h in enumerate(hints):
        hint_surface = font.render(h, True, (120, 120, 120))
        screen.blit(hint_surface, (20, 720 - (len(hints) - i - 1) * 26))

    pygame.display.flip()


pygame.quit()
sys.exit()