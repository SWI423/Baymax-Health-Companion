"""
大白脸 - 负责窗口渲染和表情状态机。
"""
import pygame
import sys
import os

# 从全局配置读取
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    FRAMES_PATH, FONT_PATH, WINDOW_WIDTH, WINDOW_HEIGHT, FACE_SIZE,
    FRAME_OPEN, FRAME_HALF, FRAME_CLOSED, MAX_FRAME, TOTAL_FRAMES
)

# ================= 内部状态 =================
_frames = []
_screen = None
_font = None
_clock = None

_current_frame = 0.0
_mode = "idle"

_speed = 0.0
_plays_remaining = 0

_target_frame = 0.0
_move_speed = 0.0
_next_mode_after_move = "idle"
_hold_after_move = 0.0
_hold_elapsed = 0.0

_return_speed = 0.0


# ================= 初始化 =================
def init_face():
    """初始化 Pygame 窗口、加载表情帧、加载字体。"""
    global _screen, _font, _clock, _frames

    pygame.init()
    _screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("大白 Baymax")

    try:
        _font = pygame.font.Font(FONT_PATH, 22)
    except:
        _font = pygame.font.Font(None, 22)

    _frames = []
    try:
        for i in range(TOTAL_FRAMES):
            filename = f"{i:04d}.png"
            filepath = os.path.join(FRAMES_PATH, filename)
            img = pygame.image.load(filepath)
            w, h = img.get_size()
            scale = FACE_SIZE / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = pygame.transform.scale(img, (new_w, new_h))
            _frames.append(img)
        print(f"[face] 成功加载 {len(_frames)} 张表情帧")
    except Exception as e:
        print(f"[face] 加载图片失败：{e}")
        sys.exit()

    _clock = pygame.time.Clock()


def get_screen():
    return _screen


def get_clock():
    return _clock


# ================= 状态机 =================
def _go_idle():
    global _mode, _current_frame
    _mode = "idle"
    _current_frame = 0.0


def blink(speed=80.0, count=1):
    """眨眼（从 0 播到 20）。"""
    global _mode, _current_frame, _speed, _plays_remaining
    _mode = "play"
    _current_frame = 0.0
    _speed = speed
    _plays_remaining = count


def look_half(speed=15.0, hold=1.0):
    """眯眼一会儿，保持 hold 秒后自动返回。"""
    global _mode, _target_frame, _move_speed, _next_mode_after_move
    global _hold_after_move, _hold_elapsed
    _mode = "move_to"
    _target_frame = float(FRAME_HALF)
    _move_speed = speed
    _next_mode_after_move = "hold"
    _hold_after_move = hold
    _hold_elapsed = 0.0


def hold_half(speed=6.0):
    """持续眯眼（无限保持）。"""
    global _mode, _target_frame, _move_speed, _next_mode_after_move
    global _hold_after_move, _hold_elapsed
    _mode = "move_to"
    _target_frame = float(FRAME_HALF)
    _move_speed = speed
    _next_mode_after_move = "hold"
    _hold_after_move = 99999
    _hold_elapsed = 0.0


def hold_closed(speed=20.0):
    """闭眼（无限保持）。"""
    global _mode, _target_frame, _move_speed, _next_mode_after_move
    global _hold_after_move, _hold_elapsed
    _mode = "move_to"
    _target_frame = float(FRAME_CLOSED)
    _move_speed = speed
    _next_mode_after_move = "hold"
    _hold_after_move = 99999
    _hold_elapsed = 0.0


def open_eyes(speed=15.0):
    """平滑恢复睁眼。"""
    global _mode, _return_speed
    _mode = "return_to_open"
    _return_speed = speed


# ================= 每帧更新与绘制 =================
def update(dt):
    """更新状态机，需要在主循环中每帧调用。"""
    global _current_frame, _mode, _hold_elapsed, _plays_remaining

    if _mode == "play":
        _current_frame += _speed * dt
        if _current_frame >= MAX_FRAME:
            _plays_remaining -= 1
            if _plays_remaining > 0:
                _current_frame = 0.0
            else:
                _go_idle()

    elif _mode == "move_to":
        if _current_frame < _target_frame:
            _current_frame += _move_speed * dt
            if _current_frame >= _target_frame:
                _current_frame = _target_frame
                _mode = _next_mode_after_move
                _hold_elapsed = 0.0
        elif _current_frame > _target_frame:
            _current_frame -= _move_speed * dt
            if _current_frame <= _target_frame:
                _current_frame = _target_frame
                _mode = _next_mode_after_move
                _hold_elapsed = 0.0
        else:
            _mode = _next_mode_after_move
            _hold_elapsed = 0.0

    elif _mode == "hold":
        _hold_elapsed += dt
        if _hold_elapsed >= _hold_after_move:
            open_eyes(15.0)

    elif _mode == "return_to_open":
        if _current_frame > FRAME_OPEN:
            _current_frame -= _return_speed * dt
            if _current_frame <= FRAME_OPEN:
                _go_idle()
        else:
            _go_idle()


def draw():
    """绘制当前帧和状态信息。"""
    _screen.fill((240, 240, 245))
    idx = max(0, min(int(round(_current_frame)), len(_frames) - 1))
    rect = _frames[idx].get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
    _screen.blit(_frames[idx], rect)

    # 左上角状态显示
    status = _font.render(f"帧: {idx:02d}  |  模式: {_mode}", True, (50, 50, 50))
    _screen.blit(status, (20, 20))


def get_current_mode():
    return _mode