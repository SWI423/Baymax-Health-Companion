# -*- coding: utf-8 -*-
"""面板三页：聊天（本轮对话+流式）/ 记忆（只读）/ 提醒（增删）"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
)
from core import memory, brain


# ============================================================
# 聊天页：只显示本轮对话，手动输入
# ============================================================
class ChatPage(QWidget):
    send_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._typing = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.view = QTextBrowser()
        self.view.setStyleSheet("""
            QTextBrowser { background: rgba(255,255,255,0.72); border: 1.5px solid #93c5fd;
                            border-radius: 14px; font-size: 14px; color: #334155; }
        """)
        v.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("和大白说点什么…（回车发送）")
        self.input.setStyleSheet("""
            QLineEdit { background: rgba(255,255,255,0.85); border: 1px solid #cbd8e8;
                        border-radius: 14px; padding: 8px 12px; font-size: 14px; color: #334155; }
        """)
        self.input.returnPressed.connect(self._send)
        self.btn = QPushButton("发送")
        self.btn.setStyleSheet("""
            QPushButton { background: #3b82f6; color: white; border: none;
                          border-radius: 14px; padding: 8px 18px; font-size: 14px; }
            QPushButton:disabled { background: #93c5fd; }
        """)
        self.btn.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn)
        v.addLayout(row)

    def _send(self):
        text = self.input.text().strip()
        if not text or self._typing:
            return
        self._typing = True
        self.btn.setEnabled(False)
        self.input.setEnabled(False)
        self.clear_round()
        self.view.append(f"<b style='color:#1e40af'>你：</b>{self._html_escape(text)}")
        self.send_requested.emit(text)

    def append_bot_start(self):
        self.view.append("<b style='color:#16a34a'>(●––●)：</b>")

    def append_bot_chunk(self, chunk):
        self.view.insertPlainText(chunk)
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append_bot_line(self, text):
        """状态机口播（招呼/提醒/告别/完成等）：完整一句"""
        if text:
            self.view.append(f"<b style='color:#16a34a'>(●––●)：</b>{self._html_escape(text)}")

    def append_user(self, text):
        if text:
            self.view.append(f"<b style='color:#1e40af'>你：</b>{self._html_escape(text)}")

    def finish_round(self, reply, emotion):
        self._typing = False
        self.btn.setEnabled(True)
        self.input.setEnabled(True)
        self.input.clear()
        if not reply:
            self.append_bot_start()
            self.append_bot_chunk("（抱歉，刚才卡住了）")

    def release_input(self):
        """只恢复输入状态（休眠/告别后），不追加任何文案"""
        self._typing = False
        self.btn.setEnabled(True)
        self.input.setEnabled(True)

    def clear_round(self):
        self.view.clear()

    @staticmethod
    def _html_escape(t):
        return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ============================================================
# 记忆页：只读展示记忆点
# ============================================================
class MemoryPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        tip = QLabel("🧠 大白记住的事（只读 · 最多 200 条）")
        tip.setStyleSheet("color:#64748b;font-size:12px;")
        v.addWidget(tip)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["内容", "来源", "重要度", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background: rgba(255,255,255,0.6); border: none;
                           border-radius: 14px; font-size: 13px; color: #334155;
                           gridline-color: #e2e8f0; }
            QHeaderView::section { background: rgba(226,232,240,0.7); border: none;
                                   padding: 4px; font-size: 12px; color: #475569; }
        """)
        v.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        rows = memory.get_all_memory_points()
        rows = sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)[:200]
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("content", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("source", ""))))
            self.table.setItem(i, 2, QTableWidgetItem(str(r.get("importance", ""))))
            created = str(r.get("created_at") or "")[:16]
            self.table.setItem(i, 3, QTableWidgetItem(created))


# ============================================================
# 提醒页：管理闹钟和提醒
# ============================================================
class ReminderPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        tip = QLabel("⏰ 大白帮你记的提醒（日期可填：明天 / 下周一 / 2026-11-01）")
        tip.setStyleSheet("color:#64748b;font-size:12px;")
        v.addWidget(tip)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["事项", "时间", "日期", "频率", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background: rgba(255,255,255,0.6); border: none;
                           border-radius: 14px; font-size: 13px; color: #334155;
                           gridline-color: #e2e8f0; }
            QHeaderView::section { background: rgba(226,232,240,0.7); border: none;
                                   padding: 4px; font-size: 12px; color: #475569; }
        """)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.inp_event = QLineEdit()
        self.inp_event.setPlaceholderText("事项，如：吃药")
        self.inp_time = QLineEdit()
        self.inp_time.setPlaceholderText("时间，如：09:00")
        self.inp_date = QLineEdit()
        self.inp_date.setPlaceholderText("日期（可空/明天/下周一）")
        btn_add = QPushButton("＋ 添加")
        btn_add.clicked.connect(self._add)
        btn_del = QPushButton("－ 删除")
        btn_del.clicked.connect(self._del)
        for w in (self.inp_event, self.inp_time, self.inp_date):
            w.setStyleSheet("""
                QLineEdit { background: rgba(255,255,255,0.85); border: 1px solid #cbd8e8;
                            border-radius: 10px; padding: 5px 8px; font-size: 13px; color: #334155; }
            """)
        btn_add.setStyleSheet("QPushButton { background:#3b82f6; color:white; border:none; border-radius:10px; padding:6px 10px; font-size:13px; }")
        btn_del.setStyleSheet("QPushButton { background:#e11d48; color:white; border:none; border-radius:10px; padding:6px 10px; font-size:13px; }")
        row.addWidget(self.inp_event, 2)
        row.addWidget(self.inp_time, 1)
        row.addWidget(self.inp_date, 2)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        v.addLayout(row)
        self.refresh()

    def _add(self):
        event = self.inp_event.text().strip()
        t = self.inp_time.text().strip()
        d = self.inp_date.text().strip()
        if not event or not t:
            return
        # 复用大脑工具函数：同一套时间/相对日期解析逻辑
        brain.TOOL_REGISTRY["set_reminder"](event_name=event, time=t, date=d)
        self.inp_event.clear(); self.inp_time.clear(); self.inp_date.clear()
        self.refresh()

    def _del(self):
        row = self.table.currentRow()
        if row < 0:
            return
        event = self.table.item(row, 0).text()
        memory.cancel_reminder(event)
        self.refresh()

    def refresh(self):
        rows = memory.get_all_reminders()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("event_name", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("time", ""))))
            self.table.setItem(i, 2, QTableWidgetItem(str(r.get("date") or "每天")))
            self.table.setItem(i, 3, QTableWidgetItem(str(r.get("frequency", ""))))
            self.table.setItem(i, 4, QTableWidgetItem(str(r.get("status", ""))))
