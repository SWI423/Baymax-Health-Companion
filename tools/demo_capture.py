# -*- coding: utf-8 -*-
"""演示素材录制 v4（专门情景版）：
    把桌宠移到屏幕中部（避开任务栏/托盘），背景纯净壁纸；
    休眠→唤醒→招呼+完整面板→徽章 每个情景从容拍摄，GIF 5.5s 流畅。
    输出 D:\\Baymax_Demo\\
"""
import os
import sys
import ctypes
import atexit
from ctypes import wintypes

ctypes.windll.user32.SetProcessDPIAware()   # 物理像素统一
user32 = ctypes.windll.user32
WORK_W = user32.GetSystemMetrics(78)
WORK_H = user32.GetSystemMetrics(79)
WORK_X = user32.GetSystemMetrics(76)
WORK_Y = user32.GetSystemMetrics(77)

# ---------- 窗口管理：录制时最小化其他窗口，退出自动恢复 ----------
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
SW_MINIMIZE, SW_RESTORE = 6, 9
_SAVED_WINDOWS = []
_SKIP_CLASSES = {
    "Shell_TrayWnd", "Progman", "WorkerW", "DummyDWMListenerWindow",
    "EdgeUiInputTopWndClass", "Windows.UI.Core.CoreWindow",
}


def _enum_cb(hwnd, lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    cls = buf.value
    if cls in _SKIP_CLASSES or cls == "":
        return True  # 任务栏/桌面/系统层不动
    if hwnd in _SKIP:
        return True  # 桌宠自身不动
    _SAVED_WINDOWS.append(hwnd)
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    return True


_SKIP = set()


def minimize_others(my_hwnd):
    _SKIP.add(my_hwnd)
    for _ in range(2):   # 枚举两轮，确保漏网窗口也最小化
        user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)
    # 保险：确保桌宠窗口不被误最小化/隐藏
    my_hw = wintypes.HWND(my_hwnd)
    if user32.IsIconic(my_hw):
        user32.ShowWindow(my_hw, SW_RESTORE)
    if not user32.IsWindowVisible(my_hw):
        user32.ShowWindow(my_hw, 5)  # SW_SHOW
    print(f"已最小化 {len(_SAVED_WINDOWS)} 个其他窗口（录制完自动恢复，桌宠状态已校验）")


@atexit.register
def restore_windows():
    for hwnd in _SAVED_WINDOWS:
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
        except Exception:
            pass
    if _SAVED_WINDOWS:
        print(f"已恢复 {len(_SAVED_WINDOWS)} 个窗口")


# ---------- 位置探测：最小化后找无图标壁纸区 ----------
def clean_score(bbox):
    img = ImageGrab.grab(bbox=bbox).convert("L")
    w, h = img.size
    px = list(img.getdata())
    score = 0
    step = 2
    for y in range(step, h, step):
        for x in range(step, w, step):
            d = abs(px[y * w + x] - px[(y - step) * w + x])
            if d > 40:
                score += 1
    return score


def choose_clean_position():
    """探测中间空白区（用户清理出来的位置），选最干净处放窗口"""
    candidates = [
        (WORK_X + 1240, WORK_Y + 420), (WORK_X + 1100, WORK_Y + 420),
        (WORK_X + 900, WORK_Y + 420), (WORK_X + 1240, WORK_Y + 560),
        (WORK_X + 1100, WORK_Y + 560), (WORK_X + 900, WORK_Y + 560),
    ]
    best, best_score = None, None
    for (x, y) in candidates:
        sc = clean_score((x - 20, y - 20, x + PET_W + 440 + 40, y + PET_H + 40))
        if best_score is None or sc < best_score:
            best_score, best = sc, (x, y)
    print(f"已选最干净位置 {best}（脏度分 {best_score}）")
    return best

from PIL import Image, ImageGrab

ROOT = r"D:\program\PythonProject\Baymax"
OUT_DIR = r"D:\Baymax_Demo"
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from desktop.baymax_pet import PetWindow, ReminderBubble
from desktop.baymax_panel import PanelWindow
from desktop.fsm_adapter import FsmAdapter
from desktop.settings_dialog import load_user_prompts
from core import brain
from core.scheduler import ReminderScheduler

# 窗口位置：固定右下壁纸区（无桌面图标，v2 验证干净），面板向左展开
PET_W, PET_H = 270, 152
# 窗口位置：固定屏幕中间空白区（用户已清理图标，录制时配合最小化豆包）
PET_W, PET_H = 270, 152
PET_X = WORK_X + 1240
PET_Y = WORK_Y + 560
BADGE_HOVER = (PET_X + 135, PET_Y + 40)
print(f"工作区 {WORK_W}x{WORK_H} 大头 @ ({PET_X},{PET_Y})")


def pet_bbox(pad=14):
    # 大头本体 + 徽章可能出现的左侧区域
    return (PET_X - 76, PET_Y - 20, PET_X + PET_W + pad, PET_Y + PET_H + pad)


def panel_bbox(pad=24):
    # 完整圈住：左侧 440 面板 + 右侧大头
    return (PET_X - 440 - pad, PET_Y - 40, PET_X + PET_W + pad, PET_Y + PET_H + pad)


def shot(name, bbox):
    img = ImageGrab.grab(bbox=bbox)
    img.save(os.path.join(OUT_DIR, name))
    print("已保存", name, img.size)


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

brain.load_history()
brain.backfill_name_from_profile()
saved = load_user_prompts()
parts = [f"{k}：{v}" for k, v in saved.items() if v.strip()]
if parts:
    brain.set_persona_extra("\n".join(parts))

pet = PetWindow()
panel = PanelWindow()
bubble = ReminderBubble()
adapter = FsmAdapter(pet, panel, bubble)
scheduler = ReminderScheduler(on_due=adapter.reminder_due)
scheduler.start()


def open_panel():
    panel.show_near(pet.frameGeometry())
    panel.memory_page.refresh()
    panel.reminder_page.refresh()


pet.panel_requested.connect(open_panel)
pet.wake_clicked.connect(adapter.wake)
panel.close_requested.connect(panel.hide)
panel.send_requested.connect(adapter.user_input)
panel.settings_requested.connect(lambda: None)

pet.move(PET_X, PET_Y)   # 移到屏幕中间空白区（用户已清理）
pet.show()
# 用户配合最小化豆包即可，脚本不再自动最小化（避免误伤桌宠窗口）

# ---------------- 录制阶段（每个情景从容拍） ----------------
frames = []
FPS = 7
GIF_SECS = 5.5


def record_frame():
    img = ImageGrab.grab(bbox=panel_bbox())
    img = img.resize((int(img.width * 0.72), int(img.height * 0.72)), Image.LANCZOS)
    frames.append(img)


def finish_gif():
    if not frames:
        return
    frames[0].save(os.path.join(OUT_DIR, "demo.gif"), save_all=True,
                   append_images=frames[1:], duration=100, loop=0, optimize=False)
    print(f"GIF 已保存：{len(frames)} 帧")


def do_badge():
    user32.SetCursorPos(*BADGE_HOVER)
    # 等徽章上抛动画稳定（1.6s）再拍
    QTimer.singleShot(1600, lambda: (shot("03_badge.png", pet_bbox()), app.quit()))


def do_wake():
    gif_timer = QTimer()
    gif_timer.timeout.connect(record_frame)
    gif_timer.start(int(1000 / FPS))
    adapter.wake()   # 唤醒 → 打招呼 → 面板自动弹出
    # 唤醒后 2.0s：面板完整 + 招呼语稳定（宽限期 2.5s 内）
    QTimer.singleShot(2000, lambda: shot("02_wake_chat.png", panel_bbox()))
    # GIF 5.5s 结束 → 徽章
    QTimer.singleShot(int(GIF_SECS * 1000), lambda: (gif_timer.stop(), finish_gif(), do_badge()))


def do_sleep_shot():
    shot("01_sleep.png", pet_bbox())          # 休眠闭眼稳定态
    QTimer.singleShot(500, do_wake)


QTimer.singleShot(4000, do_sleep_shot)   # 启动 4s：闭眼动画早已完成，拍稳定休眠
print("录制开始（中部窗口，休眠→唤醒→面板→徽章）...")
sys.exit(app.exec())
