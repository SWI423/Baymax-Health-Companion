# -*- coding: utf-8 -*-
"""素材预处理 v2：黑底渲染帧 → 透明帧（flood-fill 背景分离，保留黑眼睛）
v1 的"去黑底"会把黑色眼睛和黑背景一起删掉；本版从图像四边 flood-fill
连通的黑背景，白色身体保留，被身体包围的内部黑像素（眼睛/嘴）保留。
用法：python tools/prepare_pet_assets.py
"""
import os
import sys
from collections import deque

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "assets", "frames")
OUT_DIR = os.path.join(ROOT, "assets", "pet", "frames_pet")
BG_THR = 60          # 亮度低于此值视为黑背景/黑像素
EDGE_THR = 120       # bbox 裁剪时忽略的浅透明
OUT_W = 320          # 输出宽度（统一 bbox 后缩放）


def cutout_by_floodfill(img):
    """黑底去背：边缘连通的暗区=背景→透明；身体内部黑像素（眼睛）保留"""
    gray = np.asarray(img.convert("L"), dtype=np.int16)
    h, w = gray.shape
    # 种子：四条边上的暗像素
    seeds = set()
    for x in range(w):
        if gray[0, x] < BG_THR:
            seeds.add((x, 0))
        if gray[h - 1, x] < BG_THR:
            seeds.add((x, h - 1))
    for y in range(h):
        if gray[y, 0] < BG_THR:
            seeds.add((0, y))
        if gray[y, w - 1] < BG_THR:
            seeds.add((w - 1, y))
    if not seeds:
        return img.convert("RGBA")

    bg = np.zeros((h, w), dtype=bool)
    q = deque()
    for x, y in seeds:
        bg[y, x] = True
        q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not bg[ny, nx] and gray[ny, nx] < BG_THR:
                bg[ny, nx] = True
                q.append((nx, ny))

    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8).copy()
    rgba[bg, 3] = 0
    return Image.fromarray(rgba)


def crop_and_resize(img, out_w=OUT_W):
    """按非透明区域统一 bbox 裁剪后缩放到 out_w"""
    a = np.asarray(img.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(a > EDGE_THR)
    if len(xs) == 0:
        return img
    x0, x1 = xs.min(), xs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    # 统一 bbox：所有帧裁同一范围（先收集再裁，这里按单帧保守处理）
    cropped = img.crop((x0, y0, x1, y1))
    w, h = cropped.size
    nh = int(h * out_w / w)
    return cropped.resize((out_w, nh), Image.Resampling.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(SRC_DIR) if f.endswith(".png"))
    print(f"共 {len(files)} 帧，开始 flood-fill 抠图...")

    # 第一遍：全部抠图 + 计算统一 bbox
    cut = {}
    all_x0 = all_y0 = 10 ** 9
    all_x1 = all_y1 = -1
    for f in files:
        img = Image.open(os.path.join(SRC_DIR, f))
        out = cutout_by_floodfill(img)
        a = np.asarray(out.convert("RGBA"))[:, :, 3]
        ys, xs = np.where(a > EDGE_THR)
        if len(xs):
            all_x0 = min(all_x0, xs.min())
            all_x1 = max(all_x1, xs.max() + 1)
            all_y0 = min(all_y0, ys.min())
            all_y1 = max(all_y1, ys.max() + 1)
        cut[f] = out

    print(f"统一 bbox: x[{all_x0},{all_x1}) y[{all_y0},{all_y1})")
    # 第二遍：统一裁剪 + 缩放
    for f in files:
        img = cut[f]
        cropped = img.crop((all_x0, all_y0, all_x1, all_y1))
        w, h = cropped.size
        nh = max(1, int(h * OUT_W / w))
        resized = cropped.resize((OUT_W, nh), Image.Resampling.LANCZOS)
        resized.save(os.path.join(OUT_DIR, f))
        print(f"  {f} → {resized.size}")

    print("完成。输出目录:", OUT_DIR)


if __name__ == "__main__":
    main()
