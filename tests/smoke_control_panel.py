"""临时冒烟：overlay 控制面板命令链路（preview / style / drag / pos 回传）"""
import os
import sys
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kazari_play"))

from core.overlay_client import OverlayClient  # noqa: E402

received = []

c = OverlayClient()
c.on_subtitle_pos = lambda x, y: received.append((x, y))

assert c.ensure_bidirectional(), "overlay 连接失败"
print("[1] connected")

assert c.send_preview_subtitle(), "preview_subtitle 发送失败"
print("[2] preview_subtitle sent")
time.sleep(1.0)

assert c.send_subtitle_style({
    "bg_mode": 1, "bg_r": 0.1, "bg_g": 0.1, "bg_b": 0.25, "bg_a": 0.6,
    "corner": 12, "padding": 16, "gradient": True, "grad_r": 0.3, "grad_g": 0.25,
    "grad_b": 0.4, "grad_a": 0.8, "border": True, "border_w": 1.5,
    "font": "Microsoft YaHei UI", "font_size": 26, "font_weight": 800,
    "text_r": 1, "text_g": 1, "text_b": 1, "text_a": 1,
    "outline": True, "outline_w": 1.5, "outline_a": 0.85,
    "shadow": True, "shadow_off": 2, "shadow_a": 0.5,
    "align": 0, "line_gap": 6, "max_width": 0.9,
    "pos_x": 0.5, "pos_y": 0.7, "avoid_bottom": True, "avoid_bottom_px": 60,
}), "set_subtitle_style 发送失败"
print("[3] set_subtitle_style sent")
time.sleep(1.0)

assert c.send_subtitle_drag(True), "set_subtitle_drag(on) 发送失败"
print("[4] set_subtitle_drag on")
time.sleep(1.0)
assert c.send_subtitle_drag(False), "set_subtitle_drag(off) 发送失败"
print("[5] set_subtitle_drag off")
time.sleep(0.5)

c.quit()
time.sleep(0.5)
print("[6] quit ok; pos callbacks:", received)
print("OVERLAY PANEL SMOKE PASS" if not c._proc else "WARN: overlay still running")
