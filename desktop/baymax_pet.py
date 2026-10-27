# -*- coding: utf-8 -*-
"""桌宠大头窗（完整版）
透明置顶窗 + 表情引擎（复刻 output/face.py 帧语义：0=睁/5=半/10=闭/20=上限）
+ 眨眼轮播 + 悬停徽章 + 拖动 + 点击唤醒 + 键盘传感器模拟 + 右键菜单。
帧语义与命令行版完全一致：
    sleepy → 缓慢闭眼(帧10)   greet → 快眨2次    neutral → 睁眼(帧0)+3s自动眨
    concern → 半眯(帧5)保持3s alert → 快眨2次+1s高频眨  serious → 慢速半眯保持3s
"""
import os
import sys
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QPropertyAnimation, QEasingCurve, QAbstractAnimation
from PyQt6.QtGui import QPixmap, QAction, QCursor
from PyQt6.QtWidgets import QWidget, QLabel, QMenu, QApplication, QVBoxLayout, QGraphicsOpacityEffect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES_DIR = os.path.join(ROOT, "assets", "pet", "frames_pet")
BADGE_PATH = os.path.join(ROOT, "assets", "pet", "btn_smile.png")
TICK_MS = 60            # 表情引擎时钟
FRAME_OPEN, FRAME_HALF, FRAME_CLOSED, MAX_FRAME = 0, 5, 10, 20
FACE_W = 200            # 👈 脸显示宽度（想改大头大小就改这里，如 180=更小 / 240=更大）
BADGE_W = 56
BADGE_GAP = 14


class BadgeLabel(QLabel):
    """带点击信号的徽章"""
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            e.accept()
        else:
            super().mousePressEvent(e)


class ReminderBubble(QLabel):
    """到点提醒气泡：大头上方，5 秒后消失"""
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWordWrap(True)
        self.setMaximumWidth(360)
        self.setStyleSheet("""
            background: rgba(59, 130, 246, 0.92); color: white;
            border-radius: 16px; padding: 12px 18px; font-size: 14px;
        """)
        self.hide()

    def show_reminder(self, text, near_rect):
        self.setText(text)
        self.adjustSize()
        scr = QApplication.primaryScreen().availableGeometry()
        x = near_rect.center().x() - self.width() // 2
        y = near_rect.top() - self.height() - 14
        x = min(max(x, scr.left() + 8), scr.right() - self.width() - 8)
        y = max(y, scr.top() + 8)
        self.move(x, y)
        self.show()
        self.raise_()
        QTimer.singleShot(5000, self.hide)


class PetWindow(QWidget):
    panel_requested = pyqtSignal()
    wake_clicked = pyqtSignal()          # 点击脸（唤醒/聚焦）
    sensor_key = pyqtSignal(str)         # 键盘模拟：w/f/t → adapter
    hover_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._frames = self._load_frames()
        self._dragging = False
        self._drag_offset = QPoint()
        self._press_pos = None
        self._badge_visible = False

        # ---- 表情引擎状态（复刻 face.py）----
        self._current_frame = 0.0
        self._mode = "idle"              # idle/play/move_to/hold/return_to_open
        self._current_emotion = None     # None：允许首次 set_emotion 生效
        self._speed = 0.0
        self._plays_remaining = 0
        self._target_frame = 0.0
        self._move_speed = 0.0
        self._next_mode_after_move = "idle"
        self._hold_after_move = 0.0
        self._hold_elapsed = 0.0
        self._return_speed = 0.0
        self._auto_blink_timer = 0.0
        self._next_blink_interval = 3.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_sized = False        # 窗口尺寸只定一次（避免动画时 resize 抖动）
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

        # 徽章（先于 _apply_frame 创建）
        self._badge = BadgeLabel(self)
        pm = QPixmap(BADGE_PATH)
        self._badge.setPixmap(pm.scaled(
            BADGE_W, int(pm.height() * BADGE_W / pm.width()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self._badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._badge.hide()
        self._badge_op = QGraphicsOpacityEffect(self._badge)
        self._badge_op.setOpacity(0.0)
        self._badge.setGraphicsEffect(self._badge_op)
        self._badge.clicked.connect(self.panel_requested.emit)
        self._pos_anim = None                 # 上抛动画句柄（防漂移基准）
        self._badge_home = QPoint(0, 0)       # 徽章基准位置

        # 表情时钟
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(lambda: self.tick(TICK_MS / 1000.0))
        self._tick_timer.start(TICK_MS)

        self.set_emotion("sleepy")   # 启动即休眠（缓慢闭眼）
        self._apply_frame()
        self._move_to_default_pos()

    # ---------- 帧与显示 ----------
    def _load_frames(self):
        files = sorted(f for f in os.listdir(FRAMES_DIR) if f.endswith(".png"))
        out = []
        for f in files:
            pm = QPixmap(os.path.join(FRAMES_DIR, f))
            out.append(pm.scaled(
                FACE_W, int(pm.height() * FACE_W / pm.width()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        return out

    def _apply_frame(self):
        idx = max(FRAME_OPEN, min(int(round(self._current_frame)), len(self._frames) - 1))
        pm = self._frames[idx]
        if self._frame_sized:
            # 后续只换图，不再 resize 窗口（避免表情动画时抽动）
            self._label.setPixmap(pm)
            return
        self._frame_sized = True
        self._label.setPixmap(pm)
        badge_zone = BADGE_W + BADGE_GAP
        self._label.move(badge_zone, 0)
        self._label.resize(pm.size())
        self.resize(pm.width() + badge_zone, pm.height())
        self._reposition_badge()

    # ---------- 表情引擎（复刻 face.py）----------
    def _go_idle(self):
        self._mode = "idle"
        self._current_frame = float(FRAME_OPEN)

    def _blink(self, speed=80.0, count=1):
        self._mode = "play"
        self._current_frame = float(FRAME_OPEN)
        self._speed = speed
        self._plays_remaining = count

    def _look_half(self, speed=15.0, hold=1.0):
        self._mode = "move_to"
        self._target_frame = float(FRAME_HALF)
        self._move_speed = speed
        self._next_mode_after_move = "hold"
        self._hold_after_move = hold
        self._hold_elapsed = 0.0

    def _hold_half(self, speed=6.0):
        self._look_half(speed, 99999)

    def _hold_closed(self, speed=20.0):
        self._mode = "move_to"
        self._target_frame = float(FRAME_CLOSED)
        self._move_speed = speed
        self._next_mode_after_move = "hold"
        self._hold_after_move = 99999
        self._hold_elapsed = 0.0

    def _open_eyes(self, speed=15.0):
        self._mode = "return_to_open"
        self._return_speed = speed

    _RETRIGGER = {"concern", "serious"}

    def set_emotion(self, name):
        if self._current_emotion == name:
            if name not in self._RETRIGGER or self._mode != "idle":
                return
        self._current_emotion = name
        if name == "sleepy":
            self._hold_closed(speed=6.0)      # 👈 休眠闭眼速度（帧0→10；6.0≈1.7秒，越大越快）
        elif name == "greet":
            self._blink(speed=100.0, count=2)
            self._next_blink_interval = 3.0
        elif name == "concern":
            self._look_half(speed=10.0, hold=3.0)
        elif name == "alert":
            self._blink(speed=100.0, count=2)
            self._next_blink_interval = 1.0
        elif name == "serious":
            self._look_half(speed=5.0, hold=3.0)
        elif name == "neutral":
            self._open_eyes(speed=15.0)
            self._next_blink_interval = 3.0

    def tick(self, dt):
        if self._mode == "idle" and self._current_emotion in ("neutral", "alert"):
            self._auto_blink_timer += dt
            if self._auto_blink_timer >= self._next_blink_interval:
                self._auto_blink_timer = 0.0
                speed = 100.0 if self._current_emotion == "alert" else 60.0
                self._blink(speed=speed, count=1)

        if self._mode == "play":
            self._current_frame += self._speed * dt
            if self._current_frame >= MAX_FRAME:
                self._plays_remaining -= 1
                if self._plays_remaining > 0:
                    self._current_frame = float(FRAME_OPEN)
                else:
                    self._go_idle()
        elif self._mode == "move_to":
            if self._current_frame < self._target_frame:
                self._current_frame += self._move_speed * dt
                if self._current_frame >= self._target_frame:
                    self._current_frame = self._target_frame
                    self._mode = self._next_mode_after_move
                    self._hold_elapsed = 0.0
            elif self._current_frame > self._target_frame:
                self._current_frame -= self._move_speed * dt
                if self._current_frame <= self._target_frame:
                    self._current_frame = self._target_frame
                    self._mode = self._next_mode_after_move
                    self._hold_elapsed = 0.0
            else:
                self._mode = self._next_mode_after_move
                self._hold_elapsed = 0.0
        elif self._mode == "hold":
            self._hold_elapsed += dt
            if self._hold_elapsed >= self._hold_after_move:
                self._open_eyes(15.0)
        elif self._mode == "return_to_open":
            if self._current_frame > FRAME_OPEN:
                self._current_frame -= self._return_speed * dt
                if self._current_frame <= FRAME_OPEN:
                    self._go_idle()
            else:
                self._go_idle()

        self._apply_frame()

    # ---------- 徽章 ----------
    def _reposition_badge(self):
        """只更新徽章基准位置；动画运行时不动它（避免与上抛动画抢位置导致漂移）"""
        bh = self._badge.pixmap().height()
        self._badge_home = QPoint(0, max(0, (self.height() - bh) // 2))
        if self._pos_anim is None or self._pos_anim.state() != QAbstractAnimation.State.Running:
            self._badge.move(self._badge_home)

    def _fade_badge(self, show):
        self._badge_visible = show
        if show:
            self._badge.show()
            self._badge.move(self._badge_home)   # 先归位，动画从基准位置抛起
            start = QPoint(self._badge_home.x(), self._badge_home.y() + 30)
            self._pos_anim = QPropertyAnimation(self._badge, b"pos", self)
            self._pos_anim.setDuration(450)
            self._pos_anim.setStartValue(start)
            self._pos_anim.setEndValue(self._badge_home)
            self._pos_anim.setEasingCurve(QEasingCurve.Type.OutBounce)
            self._pos_anim.start()
        else:
            self._pos_anim = None
        op_anim = QPropertyAnimation(self._badge_op, b"opacity", self)
        op_anim.setDuration(200)
        op_anim.setStartValue(self._badge_op.opacity())
        op_anim.setEndValue(1.0 if show else 0.0)
        op_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        op_anim.finished.connect(lambda: self._badge.hide() if not show else None)
        op_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---------- 位置 ----------
    def _move_to_default_pos(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - self.width() - 60
        y = screen.y() + screen.height() - self.height() - 24
        self.move(x, y)

    # ---------- 点击脸=唤醒 / 拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = e.globalPosition().toPoint()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._dragging = False
        if e.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            moved = (e.globalPosition().toPoint() - self._press_pos).manhattanLength()
            self._press_pos = None
            if moved < 6:              # 几乎没移动 = 点击 → 唤醒
                self.wake_clicked.emit()

    # ---------- 键盘传感器模拟（W/F/H/T） ----------
    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_W:
            self.sensor_key.emit("w")
        elif key == Qt.Key.Key_F:
            self.sensor_key.emit("f")
        elif key == Qt.Key.Key_H:
            self.sensor_key.emit("h")
        elif key == Qt.Key.Key_T:
            self.sensor_key.emit("t")
        else:
            super().keyPressEvent(e)

    # ---------- 悬停 ----------
    def enterEvent(self, e):
        self.hover_changed.emit(True)
        self._fade_badge(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        cursor_global = QCursor.pos()
        if self._badge_visible and self._badge.geometry().contains(self.mapFromGlobal(cursor_global)):
            return
        self.hover_changed.emit(False)
        self._fade_badge(False)
        super().leaveEvent(e)

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        act_panel = QAction("🖥 打开面板", self)
        act_panel.triggered.connect(self.panel_requested.emit)
        act_wake = QAction("🔆 唤醒大白", self)
        act_wake.triggered.connect(self.wake_clicked.emit)
        act_close = QAction("👋 退出大白", self)
        act_close.triggered.connect(QApplication.instance().quit)
        menu.addAction(act_panel)
        menu.addAction(act_wake)
        menu.addAction(act_close)
        menu.exec(e.globalPos())
