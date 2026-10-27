# -*- coding: utf-8 -*-
"""设置弹窗（M4）：只编辑白名单人设补充，持久化到 data/user_prompts.json
核心提示词（人设全量 / Pass2 / 工具说明书）硬编码，此处无 UI 入口。
"""
import os
import json
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QTextEdit, QPushButton, QHBoxLayout,
    QLabel,
)
from config import USER_TWEAKABLE_PROMPTS_DEFAULTS, USER_PROMPTS_FILE


def load_user_prompts():
    """读持久化文件；无文件/损坏则用默认值"""
    defaults = dict(USER_TWEAKABLE_PROMPTS_DEFAULTS)
    try:
        if os.path.exists(USER_PROMPTS_FILE):
            with open(USER_PROMPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in defaults:
                if k in data and isinstance(data[k], str) and data[k].strip():
                    defaults[k] = data[k]
    except Exception:
        pass
    return defaults


def save_user_prompts(data):
    os.makedirs(os.path.dirname(USER_PROMPTS_FILE), exist_ok=True)
    with open(USER_PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("大白设置")
        self.resize(420, 320)
        self._values = load_user_prompts()
        self._edits = {}

        v = QVBoxLayout(self)
        v.setSpacing(10)

        tip = QLabel("可修改大白的简单人设补充（立即生效）。核心提示词受保护，不可在此修改。")
        tip.setStyleSheet("color:#64748b;font-size:12px;")
        tip.setWordWrap(True)
        v.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(8)
        for key in USER_TWEAKABLE_PROMPTS_DEFAULTS:
            edit = QTextEdit()
            edit.setPlaceholderText(USER_TWEAKABLE_PROMPTS_DEFAULTS[key])
            edit.setPlainText(self._values.get(key, ""))
            edit.setFixedHeight(72)
            edit.setStyleSheet("""
                QTextEdit { background: white; border: 1px solid #cbd8e8;
                            border-radius: 10px; padding: 6px; font-size: 13px; color: #334155; }
            """)
            form.addRow(f"{key}：", edit)
            self._edits[key] = edit
        v.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("QPushButton { border:1px solid #cbd8e8; border-radius:10px; padding:6px 16px; font-size:13px; color:#334155; }")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("保存")
        btn_save.setStyleSheet("QPushButton { background:#3b82f6; color:white; border:none; border-radius:10px; padding:6px 16px; font-size:13px; }")
        btn_save.clicked.connect(self._save)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        v.addLayout(btns)

    def _save(self):
        from core import brain
        data = {}
        parts = []
        for key, edit in self._edits.items():
            val = edit.toPlainText().strip()
            if val:
                data[key] = val
                parts.append(f"{key}：{val}")
        save_user_prompts(data)
        brain.set_persona_extra("\n".join(parts))
        self.accept()
