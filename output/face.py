import pygame
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import console
from config import (
    FRAMES_PATH, FONT_PATH, WINDOW_WIDTH, WINDOW_HEIGHT, FACE_SIZE,
    FRAME_OPEN, FRAME_HALF, FRAME_CLOSED, MAX_FRAME, TOTAL_FRAMES
)

_frames = []
_screen = None
_font = None
_clock = None

_current_frame = 0.0
_mode = "idle"
_current_emotion = "neutral"

_speed = 0.0
_plays_remaining = 0

_target_frame = 0.0
_move_speed = 0.0
_next_mode_after_move = "idle"
_hold_after_move = 0.0
_hold_elapsed = 0.0
_return_speed = 0.0
_auto_blink_timer = 0.0
_next_blink_interval = 3.0

def init_face():
    global _screen, _font, _clock, _frames
    pygame.init()
    _screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("大白 Baymax")
    try: _font = pygame.font.Font(FONT_PATH, 22)
    except: _font = pygame.font.Font(None, 22)

    _frames = []
    try:
        for i in range(TOTAL_FRAMES):
            filepath = os.path.join(FRAMES_PATH, f"{i:04d}.png")
            img = pygame.image.load(filepath)
            w, h = img.get_size()
            scale = FACE_SIZE / max(w, h)
            img = pygame.transform.scale(img, (int(w * scale), int(h * scale)))
            _frames.append(img)
    except Exception as e:
        print(f"[face] 加载图片失败：{e}")
        sys.exit()
    _clock = pygame.time.Clock()

def _go_idle():
    global _mode, _current_frame
    _mode = "idle"
    _current_frame = 0.0

def blink(speed=80.0, count=1):
    global _mode, _current_frame, _speed, _plays_remaining
    _mode = "play"
    _current_frame = 0.0
    _speed = speed
    _plays_remaining = count

def look_half(speed=15.0, hold=1.0):
    global _mode, _target_frame, _move_speed, _next_mode_after_move, _hold_after_move, _hold_elapsed
    _mode = "move_to"
    _target_frame = float(FRAME_HALF)
    _move_speed = speed
    _next_mode_after_move = "hold"
    _hold_after_move = hold
    _hold_elapsed = 0.0

def hold_half(speed=6.0):
    global _mode, _target_frame, _move_speed, _next_mode_after_move, _hold_after_move, _hold_elapsed
    _mode = "move_to"
    _target_frame = float(FRAME_HALF)
    _move_speed = speed
    _next_mode_after_move = "hold"
    _hold_after_move = 99999
    _hold_elapsed = 0.0

def hold_closed(speed=20.0):
    global _mode, _target_frame, _move_speed, _next_mode_after_move, _hold_after_move, _hold_elapsed
    _mode = "move_to"
    _target_frame = float(FRAME_CLOSED)
    _move_speed = speed
    _next_mode_after_move = "hold"
    _hold_after_move = 99999
    _hold_elapsed = 0.0

def open_eyes(speed=15.0):
    global _mode, _return_speed
    _mode = "return_to_open"
    _return_speed = speed

# 演完后可以重新触发的瞬时表情：
# LLM 思考要好几秒，concern 的 3 秒保持早在"精准覆盖"到来之前就播完了；
# 若不支持重触发，覆盖同一情绪时会哑火（脸上毫无变化）。
_RETRIGGER_EMOTIONS = {"concern", "serious"}

def set_emotion(emotion_name):
    global _current_emotion, _auto_blink_timer, _next_blink_interval
    if _current_emotion == emotion_name:
        # 同一情绪：瞬时表情在动画演完后应能再次触发（否则精准覆盖会哑火）；
        # 动画播放中则不重启，否则主循环每帧调用会把动画无限摁在起点
        if emotion_name not in _RETRIGGER_EMOTIONS or _mode != "idle":
            return

    _current_emotion = emotion_name
    console.debug(f"切换情绪: {emotion_name}")

    if emotion_name == "sleepy":
        # 👈 缓慢闭眼：帧速 4.0（10帧 ÷ 4 ≈ 2.5 秒），比默认 20.0 更舒缓，符合"渐渐睡去"
        hold_closed(speed=4.0)
    elif emotion_name == "greet":
        blink(speed=100.0, count=2)
        _next_blink_interval = 3.0
    elif emotion_name == "concern":
        # 👈 用 look_half，眯眼保持 3 秒后，自动平滑睁开
        look_half(speed=10.0, hold=3.0)
    elif emotion_name == "alert":
        blink(speed=100.0, count=2)
        _next_blink_interval = 1.0
    elif emotion_name == "serious":
        # 👈 沉重地半眯眼，保持 3 秒后自动平滑睁开
        look_half(speed=5.0, hold=3.0)
    elif emotion_name == "neutral":
        open_eyes(speed=15.0)
        _next_blink_interval = 3.0

def update(dt):
    global _current_frame, _mode, _hold_elapsed, _plays_remaining
    global _auto_blink_timer, _current_emotion

    if _mode == "idle" and _current_emotion in ["neutral", "alert"]:
        _auto_blink_timer += dt
        if _auto_blink_timer >= _next_blink_interval:
            _auto_blink_timer = 0.0
            speed = 100.0 if _current_emotion == "alert" else 60.0
            blink(speed=speed, count=1)

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
    _screen.fill((240, 240, 245))
    idx = max(0, min(int(round(_current_frame)), len(_frames) - 1))
    rect = _frames[idx].get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
    _screen.blit(_frames[idx], rect)

    status = _font.render(f"帧: {idx:02d} | 模式: {_mode} | 情绪: {_current_emotion}", True, (50, 50, 50))
    _screen.blit(status, (20, 20))