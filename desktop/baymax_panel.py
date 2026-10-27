# -*- coding: utf-8 -*-
"""桌宠面板窗（横屏紧凑版）
440×224 圆角卡片，白蓝灰透明科技感，面积约为原竖屏版一半。
结构：顶栏状态区(状态/情绪/记忆/动作+设置) / 左侧图标导航 / 右侧 QStackedWidget。
特性：鼠标移出面板 150ms 后自动隐藏（回到桌宠本体）；设置弹窗打开时暂停隐藏。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QTimer, QSize
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QPushButton, QApplication,
)
from desktop.panel_pages import ChatPage, MemoryPage, ReminderPage

PANEL_W, PANEL_H = 440, 224
MARGIN = 12          # 与大头的最小间距
NAV_W = 42

CARD_QSS = """
QFrame#card {
    background: rgba(244, 248, 253, 0.88);
    border: 1px solid rgba(203, 216, 232, 0.9);
    border-radius: 26px;
}
QLabel#status_state, QLabel#status_emotion, QLabel#status_memory, QLabel#status_action {
    background: rgba(59, 130, 246, 0.10);
    border: 1px solid rgba(59, 130, 246, 0.25);
    border-radius: 10px;
    color: #1e40af;
    padding: 2px 8px;
    font-size: 11px;
}
QListWidget#nav {
    background: transparent;
    border: none;
    outline: none;
    font-size: 16px;
}
QListWidget#nav::item { height: 40px; border-radius: 10px; margin: 2px 3px; }
QListWidget#nav::item:selected {
    background: rgba(59, 130, 246, 0.15);
    color: #1e40af;
}
QPushButton#tool_btn {
    background: transparent;
    border: none;
    color: #64748b;
    font-size: 15px;
    padding: 2px 6px;
}
QPushButton#tool_btn:hover { background: rgba(59, 130, 246, 0.12); border-radius: 10px; }
"""


class PanelWindow(QWidget):
    close_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    send_requested = pyqtSignal(str)   # 聊天页发送 → FsmAdapter

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(CARD_QSS)
        self.resize(PANEL_W, PANEL_H)
        self._dragging = False
        self._drag_offset = QPoint()
        self._suppress_hide = False      # 设置弹窗打开期间不自动隐藏
        self._grace_until = 0.0          # 弹出宽限期：刚弹出时鼠标还没移到面板上，暂不隐藏

        card = QFrame(self)
        card.setObjectName("card")
        card.setGeometry(0, 0, PANEL_W, PANEL_H)
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        v.addLayout(self._build_header())
        v.addLayout(self._build_body(), 1)
        self._card = card

        # 鼠标不在面板上 → 自动消失（200ms 轮询，不依赖 leaveEvent 更稳）
        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(200)
        self._hide_timer.timeout.connect(self._maybe_hide)
        self._hide_timer.start()

    # ---------- 顶栏：状态区（紧凑横排） ----------
    def _build_header(self):
        self.lbl_state = QLabel("状态：—")
        self.lbl_state.setObjectName("status_state")
        self.lbl_emotion = QLabel("情绪：—")
        self.lbl_emotion.setObjectName("status_emotion")
        self.lbl_memory = QLabel("记忆：—")
        self.lbl_memory.setObjectName("status_memory")
        self.lbl_action = QLabel("动作：—")
        self.lbl_action.setObjectName("status_action")
        btn_set = QPushButton("⚙️")
        btn_set.setObjectName("tool_btn")
        btn_set.setToolTip("设置")
        btn_set.clicked.connect(self._on_settings)
        btn_close = QPushButton("✕")
        btn_close.setObjectName("tool_btn")
        btn_close.setToolTip("关闭面板")
        btn_close.clicked.connect(self.close_requested.emit)
        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self.lbl_state)
        row.addWidget(self.lbl_emotion)
        row.addWidget(self.lbl_memory)
        row.addWidget(self.lbl_action)
        row.addStretch(1)
        row.addWidget(btn_set)
        row.addWidget(btn_close)
        return row

    # ---------- 中部：图标导航 + 页面 ----------
    def _build_body(self):
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(NAV_W)
        self.nav.setIconSize(QSize(18, 18))
        for icon, tip in [("💬", "聊天"), ("🧠", "记忆"), ("⏰", "提醒")]:
            item = QListWidgetItem(icon)
            item.setToolTip(tip)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.nav.addItem(item)
        self.nav.setCurrentRow(0)

        self.pages = QStackedWidget()
        self.chat_page = ChatPage()
        self.memory_page = MemoryPage()
        self.reminder_page = ReminderPage()
        self.chat_page.send_requested.connect(self.send_requested.emit)
        self.pages.addWidget(self.chat_page)
        self.pages.addWidget(self.memory_page)
        self.pages.addWidget(self.reminder_page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.nav)
        row.addWidget(self.pages, 1)
        return row

    # ---------- 状态区更新 ----------
    def set_status(self, state=None, emotion=None, memory=None, action=None):
        if state is not None:
            self.lbl_state.setText(f"状态：{state}")
        if emotion is not None:
            self.lbl_emotion.setText(f"情绪：{emotion}")
        if memory is not None:
            self.lbl_memory.setText(f"记忆：{memory}")
        if action is not None:
            self.lbl_action.setText(f"动作：{action}")

    # ---------- 设置（弹窗期间暂停自动隐藏） ----------
    def _on_settings(self):
        self._suppress_hide = True
        try:
            self.settings_requested.emit()
        finally:
            self._suppress_hide = False

    # ---------- 位置自适应（按大头四边剩余空间） ----------
    def show_near(self, pet_rect):
        scr = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        g = scr.availableGeometry()
        cands = [
            (pet_rect.right() + MARGIN, pet_rect.top(), g.right() - pet_rect.right()),
            (pet_rect.left() - MARGIN - PANEL_W, pet_rect.top(), pet_rect.left() - g.left()),
            (pet_rect.left(), pet_rect.bottom() + MARGIN, g.bottom() - pet_rect.bottom()),
            (pet_rect.left(), pet_rect.top() - MARGIN - PANEL_H, pet_rect.top() - g.top()),
        ]
        valid = [c for c in cands if c[2] > 60]
        x, y, _ = max(valid, key=lambda c: c[2]) if valid else cands[0]
        x = min(max(x, g.left() + MARGIN), g.right() - PANEL_W - MARGIN)
        y = min(max(y, g.top() + MARGIN), g.bottom() - PANEL_H - MARGIN)
        self.move(x, y)
        self._grace_until = time.time() + 2.5   # 👈 宽限期：2.5s 内不自动隐藏
        self.show()
        self.raise_()

    # ---------- 鼠标移出 → 自动隐藏（鼠标没停在面板上就消失） ----------
    def leaveEvent(self, e):
        if not self._suppress_hide:
            QTimer.singleShot(150, self._maybe_hide)
        super().leaveEvent(e)

    def _maybe_hide(self):
        if not self.isVisible() or self._suppress_hide:
            return
        if time.time() < self._grace_until:
            return                      # 宽限期内不隐藏（鼠标还没移到面板上）
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self.hide()

    # ---------- 面板拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._dragging = False


if __name__ == "__main__":
    from PyQt6.QtGui import QCursor
    app = QApplication(sys.argv)
    w = PanelWindow()
    w.show()
    app.exec()
