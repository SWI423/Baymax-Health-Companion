# -*- coding: utf-8 -*-
"""桌宠入口（完整迁移版）：大头窗 + 面板 + FSM 适配器 + 调度器 + 设置
运行：conda activate Baymax && python desktop/run_pet.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6.QtWidgets import QApplication
from desktop.baymax_pet import PetWindow, ReminderBubble
from desktop.baymax_panel import PanelWindow
from desktop.fsm_adapter import FsmAdapter
from desktop.settings_dialog import SettingsDialog, load_user_prompts
from core import brain
from core.state_machine import State
from core.scheduler import ReminderScheduler


def main():
    global pet, panel, adapter
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 面板关了大头还在

    # 大脑初始化（历史 + 名字回填 + 设置白名单人设注入）
    brain.load_history()
    brain.backfill_name_from_profile()
    saved = load_user_prompts()
    parts = [f"{k}：{v}" for k, v in saved.items() if v.strip()]
    if parts:
        brain.set_persona_extra("\n".join(parts))

    pet = PetWindow()          # 启动即 sleepy（缓慢闭眼）
    panel = PanelWindow()
    bubble = ReminderBubble()
    adapter = FsmAdapter(pet, panel, bubble)

    # 定时提醒 → 状态机（唤醒/提醒）
    scheduler = ReminderScheduler(on_due=adapter.reminder_due)
    scheduler.start()

    def open_panel():
        panel.show_near(pet.frameGeometry())
        panel.memory_page.refresh()
        panel.reminder_page.refresh()

    def on_sensor_key(k):
        """键盘传感器模拟：W=用户唤醒 F=摔倒传感 H=心率异常 T=定时器"""
        st = adapter.fsm.state
        if k == "w":
            adapter.fsm.handle_event("WAKE_USER")
        elif k == "f":
            adapter.fsm.handle_event(
                "WAKE_SENSOR" if st == State.SLEEP else "SENSOR_ALERT",
                payload={"kind": "fall"})
        elif k == "h":
            adapter.fsm.handle_event(
                "WAKE_SENSOR" if st == State.SLEEP else "SENSOR_ALERT",
                payload={"kind": "heart"})
        elif k == "t":
            adapter.fsm.handle_event("WAKE_TIMER" if st == State.SLEEP else "TIMER_ALERT")

    pet.panel_requested.connect(open_panel)
    pet.wake_clicked.connect(adapter.wake)
    pet.sensor_key.connect(on_sensor_key)
    panel.close_requested.connect(panel.hide)
    panel.send_requested.connect(adapter.user_input)
    panel.settings_requested.connect(lambda: SettingsDialog(panel).exec())

    pet.show()
    app.exec()


if __name__ == "__main__":
    main()
