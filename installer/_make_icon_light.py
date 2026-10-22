# -*- coding: utf-8 -*-
"""把图标从深色底改为浅色底（保留原有的点阵 "MD" 排布，只重着色）。

构建期工具，不随应用分发；依赖 Pillow（仅本机安装，运行时零依赖）。
- 逐帧处理（保留每个尺寸各自的点阵清晰度，不做 256 缩放）
- 暗色底 -> 浅色底；点阵按 x 方向重绘为更深、浅底上更易读的渐变
- 卸载图标右下角的红叉徽标：识别"纯红/近白"像素原样保留

用法：python installer/_make_icon_light.py
"""
import os
import struct
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
BACKUP = os.path.join(HERE, "icon_backup")

OLD_BG = (32, 36, 46)          # 原深色底 #20242e
NEW_BG = (247, 249, 252)       # 浅色底  #f7f9fc
# 点阵渐变（左->右）：teal -> GitHub blue -> violet -> magenta
GRAD = [(16, 160, 140), (9, 105, 218), (111, 66, 193), (191, 57, 137)]


def grad_at(tx):
    n = len(GRAD) - 1
    x = max(0.0, min(1.0, tx)) * n
    i = min(int(x), n - 1)
    f = x - i
    a, b = GRAD[i], GRAD[i + 1]
    return tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))


def is_badge(r, g, b):
    """红叉徽标（纯红 / 近白），不参与重着色。"""
    red = (r > 110 and b < 95 and g < 115 and r > g + 40)
    white = (min(r, g, b) > 210)
    return red or white


def recolor_frame(im, keep_badge):
    im = im.convert("RGBA")
    w, h = im.size
    src = im.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a < 8:
                continue
            if keep_badge and is_badge(r, g, b):
                dst[x, y] = (r, g, b, a)
                continue
            d = abs(r - OLD_BG[0]) + abs(g - OLD_BG[1]) + abs(b - OLD_BG[2])
            if d < 46:                       # 背景 -> 浅色底
                dst[x, y] = NEW_BG + (a,)
                continue
            # 点：按亮度算覆盖率（抗锯齿边缘软过渡），再按 x 位置取渐变
            t = (max(r, g, b) / 255.0 - 0.17) / 0.28
            t = max(0.0, min(1.0, t))
            gc = grad_at(x / float(max(1, w - 1)))
            col = tuple(round(NEW_BG[k] + (gc[k] - NEW_BG[k]) * t) for k in range(3))
            dst[x, y] = col + (a,)
    return out


def frames_of(path):
    """返回 [(size, RGBA image), ...]，保留每个尺寸各自的原图。"""
    im = Image.open(path)
    out = []
    for size in sorted(im.info.get("sizes", set())):
        im.size = size
        im.load()
        out.append((size, im.copy().convert("RGBA")))
    return out


def write_ico(path, frames):
    """写 PNG 帧的 ICO（与原图标同格式：Vista+ PNG 帧，csc/资源管理器均识别）。"""
    blobs = []
    for size, img in frames:
        import io
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        blobs.append((size, bio.getvalue()))
    n = len(blobs)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    dirs = b""
    data = b""
    for size, png in blobs:
        w, h = size
        dirs += struct.pack("<BBBBHHII",
                            0 if w >= 256 else w, 0 if h >= 256 else h,
                            0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(header + dirs + data)


def preview_sheet(pairs, out_path):
    """一张对比图：浅底条 / 深底条，各放 256/64/48/32/16。"""
    sizes = [256, 64, 48, 32, 16]
    pad = 18
    row_h = 256 + 2 * pad
    width = pad + sum((s + pad) for s in sizes) + pad
    sheet = Image.new("RGBA", (width, row_h * 2), (255, 255, 255, 255))
    strip_colors = [(255, 255, 255), (32, 36, 46)]
    for row, bg in enumerate(strip_colors):
        band = Image.new("RGBA", (width, row_h), bg + (255,))
        sheet.paste(band, (0, row * row_h))
        x = pad
        for s in sizes:
            img = pairs[(s, s)]
            band2 = img if img.size == (s, s) else img.resize((s, s), Image.LANCZOS)
            y = pad + (256 - s) // 2
            band.paste(band2, (x, y), band2)
            sheet.paste(band, (0, row * row_h))
            x += s + pad
    sheet.convert("RGB").save(out_path)


def main():
    os.makedirs(BACKUP, exist_ok=True)
    jobs = [("md-editor.ico", False)]
    preview = {}
    for name, badge in jobs:
        src_path = os.path.join(SRC, name)
        bak = os.path.join(BACKUP, name)
        if not os.path.exists(bak):          # 首次：把原图标留底（之后每次处理都以它为输入，脚本可重复运行）
            with open(src_path, "rb") as f:
                data = f.read()
            with open(bak, "wb") as f:
                f.write(data)
        frames = frames_of(bak)
        new_frames = [(size, recolor_frame(img, badge)) for size, img in frames]
        write_ico(src_path, new_frames)
        if name == "md-editor.ico":
            preview = {size: img for size, img in new_frames}
        print("wrote", name, "frames", [s for s, _ in new_frames])
    # 卸载图标始终由浅色主图标派生（沿用仓库既有脚本，红叉徽标风格一致）
    subprocess.run([sys.executable, os.path.join(HERE, "_make_uninstall_icon.py"),
                    os.path.join(SRC, "md-editor.ico"),
                    os.path.join(SRC, "uninstall-md.ico")],
                   cwd=SRC, check=True)
    preview_sheet(preview, os.path.join(HERE, "icon-preview.png"))
    print("preview ->", os.path.join(HERE, "icon-preview.png"))
    print("preview ->", os.path.join(HERE, "icon-preview.png"))


if __name__ == "__main__":
    main()
