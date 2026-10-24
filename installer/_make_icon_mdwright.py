# -*- coding: utf-8 -*-
"""MDWright 应用图标候选生成器（构建期工具，依赖 Pillow，不随应用分发）。

设计空间统一 256×256 单位；每个目标尺寸按档位重绘（不做 256→16 粗暴缩放），
尺寸内部 8× 超采样再 LANCZOS 收敛，保证小尺寸笔画不糊。

用法：
    python installer/_make_icon_mdwright.py                  # 生成候选预览对比图
    python installer/_make_icon_mdwright.py --ico <variant>   # 把某个候选写成 ico

候选：
    solid   —— 单色渐变描边的 M（基准款，任何尺寸都清楚）
    seam    —— 中轴留缝、左右异色的拼接 M（讲"两料咬合"）
    carved  —— 实底渐变瓷砖 + 镂空 M（最醒目）
    dot     —— 点阵 M（延续现有血统，小尺寸会糊）
"""
import math
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
OUT = os.path.join(HERE, "icon-candidates")

SS = 8                      # 超采样倍数
UNIT = 256                  # 设计空间边长

BG_LIGHT = (247, 249, 252)  # #f7f9fc
TILE = (8, 8, 248, 248)     # 圆角瓷砖外框
TILE_R = 56                 # 圆角半径

# 品牌渐变：teal -> GitHub blue -> violet -> magenta
GRAD = [(16, 160, 140), (9, 105, 218), (111, 66, 193), (191, 57, 137)]

SIZES = [16, 20, 24, 32, 48, 64, 128, 256]


# ---------------------------------------------------------------- 通用工具

def lerp_stops(stops, t):
    n = len(stops) - 1
    x = max(0.0, min(1.0, t)) * n
    i = min(int(x), n - 1)
    f = x - i
    a, b = stops[i], stops[i + 1]
    return tuple(a[k] + (b[k] - a[k]) * f for k in range(3))


def gradient_image(N, stops, angle_deg=0.0):
    """线性渐变（低分辨率算完再双三次放大，避免逐像素的 Python 循环）。"""
    g = 160
    dx = math.cos(math.radians(angle_deg))
    dy = math.sin(math.radians(angle_deg))
    span = 0.5 * (abs(dx) + abs(dy)) or 0.5
    small = Image.new("RGB", (g, g))
    px = small.load()
    for j in range(g):
        v = (j + 0.5) / g - 0.5
        for i in range(g):
            u = (i + 0.5) / g - 0.5
            t = (u * dx + v * dy) / (2.0 * span) + 0.5
            px[i, j] = tuple(round(c) for c in lerp_stops(stops, t))
    return small.resize((N, N), Image.BICUBIC)


def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l) if l else (0.0, 0.0)


def perp(v):
    return (-v[1], v[0])


def stroke_polyline(draw, pts, h):
    """把折线按半宽 h 描成实心（线段四边形 + 拐角 miter 楔），避免自交伪影。"""
    segs = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        d = unit((b[0] - a[0], b[1] - a[1]))
        segs.append((a, b, d, perp(d)))

    e = h * 0.35
    for i, (a, b, d, n) in enumerate(segs):
        a2 = (a[0] - d[0] * e, a[1] - d[1] * e) if i > 0 else a
        b2 = (b[0] + d[0] * e, b[1] + d[1] * e) if i < len(segs) - 1 else b
        draw.polygon([(a2[0] + n[0] * h, a2[1] + n[1] * h),
                      (b2[0] + n[0] * h, b2[1] + n[1] * h),
                      (b2[0] - n[0] * h, b2[1] - n[1] * h),
                      (a2[0] - n[0] * h, a2[1] - n[1] * h)], fill=255)

    for i in range(1, len(pts) - 1):
        p = pts[i]
        n1 = segs[i - 1][3]
        n2 = segs[i][3]
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        L = math.hypot(mx, my)
        if L < 1e-6:
            continue
        mx, my = mx / L, my / L
        cos_half = max(0.34, mx * n1[0] + my * n1[1])
        for sgn in (1.0, -1.0):
            k = min(h / cos_half, 1.7 * h) * sgn
            draw.polygon([p,
                          (p[0] + n1[0] * h * sgn, p[1] + n1[1] * h * sgn),
                          (p[0] + mx * k, p[1] + my * k),
                          (p[0] + n2[0] * h * sgn, p[1] + n2[1] * h * sgn)], fill=255)


# ---------------------------------------------------------------- 尺寸档位

def spec(s):
    """按目标尺寸给光学修正：小尺寸加粗笔画、放大字形、丢弃细节。"""
    if s <= 20:
        return dict(box=(44, 50, 212, 206), stroke=42, seam=0, chisel=False)
    if s <= 32:
        return dict(box=(48, 54, 208, 202), stroke=37, seam=0, chisel=False)
    if s <= 64:
        return dict(box=(52, 58, 204, 198), stroke=33, seam=8, chisel=True)
    return dict(box=(56, 60, 200, 196), stroke=30, seam=9, chisel=True)


APEX = 0.66                 # V 谷深度（占字高比例，浅谷延续原图标比例）


def m_mask(N, sp, k, chisel=True):
    """M 字形蒙版（N×N 灰度）。

    竖画画成直角矩形（顶边即 cap 线），斜画单独描边、起点让描边的上边缘
    正好切在矩形外顶角上 —— 两者顶边严丝合缝，不会留出竖的突起。
    """
    mask = Image.new("L", (N, N), 0)
    dm = ImageDraw.Draw(mask)
    t = sp["stroke"]
    x0, yt, x1, yb = sp["box"]
    cx = (x0 + x1) / 2.0
    ym = yt + (yb - yt) * APEX
    h = t / 2.0

    dm.rectangle([x0 * k, yt * k, (x0 + t) * k, yb * k], fill=255)
    dm.rectangle([(x1 - t) * k, yt * k, x1 * k, yb * k], fill=255)

    def corner(side):
        c = (x0 + t, yt) if side > 0 else (x1 - t, yt)
        d = unit((cx - c[0], ym - c[1]))
        n = perp(d)
        if n[1] > 0:
            n = (-n[0], -n[1])
        return (c[0] - n[0] * h, c[1] - n[1] * h)

    pts = [corner(1), (cx, ym), corner(-1)]
    stroke_polyline(dm, [(p[0] * k, p[1] * k) for p in pts], h * k)

    # 顶边对齐 cap 线：削掉抗锯齿溢出的一两个像素，保证顶边是干净的一条直线
    dm.rectangle([0, 0, N, yt * k], fill=0)
    dm.rectangle([x0 * k, yt * k, (x0 + t) * k, yb * k], fill=255)
    dm.rectangle([(x1 - t) * k, yt * k, x1 * k, yb * k], fill=255)

    if chisel and sp["chisel"]:
        # 只在底部两个端点做 45° 凿口
        c = t * 0.26
        for gx, sx in ((x0, 1), (x1, -1)):
            dm.polygon([(gx * k, yb * k), ((gx + sx * c) * k, yb * k),
                        (gx * k, (yb - c) * k)], fill=0)
    return mask


def tile_layer(N, k, fill=BG_LIGHT, border=True):
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([TILE[0] * k, TILE[1] * k, TILE[2] * k, TILE[3] * k],
                        radius=TILE_R * k, fill=tuple(fill) + (255,))
    if border:
        d.rounded_rectangle([TILE[0] * k, TILE[1] * k, TILE[2] * k, TILE[3] * k],
                            radius=TILE_R * k,
                            outline=(15, 23, 42, 26), width=max(1, round(1.2 * k)))
    return img


def paint_mask(base, mask, grad):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(grad, (0, 0), mask)
    return Image.alpha_composite(base, layer)


# ---------------------------------------------------------------- 四个候选

def render_solid(s):
    sp = spec(s)
    N, k = s * SS, s * SS / float(UNIT)
    mask = m_mask(N, sp, k, chisel=True)
    img = paint_mask(tile_layer(N, k), mask, gradient_image(N, GRAD, 0))
    return img.resize((s, s), Image.LANCZOS)


def render_seam(s):
    sp = spec(s)
    N, k = s * SS, s * SS / float(UNIT)
    mask = m_mask(N, sp, k, chisel=True)
    cx = (sp["box"][0] + sp["box"][2]) / 2.0 * k
    g = sp["seam"] * k
    left = Image.new("L", (N, N), 0)
    left.paste(mask.crop((0, 0, int(cx - g / 2), N)), (0, 0))
    right = Image.new("L", (N, N), 0)
    right.paste(mask.crop((int(cx + g / 2), 0, N, N)), (int(cx + g / 2), 0))
    img = tile_layer(N, k)
    img = paint_mask(img, left, gradient_image(N, [GRAD[0], GRAD[1]], 0))
    img = paint_mask(img, right, gradient_image(N, [GRAD[2], GRAD[3]], 0))
    return img.resize((s, s), Image.LANCZOS)


def render_carved(s):
    sp = spec(s)
    N, k = s * SS, s * SS / float(UNIT)
    mask = m_mask(N, sp, k, chisel=True)
    round_mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(round_mask).rounded_rectangle(
        [TILE[0] * k, TILE[1] * k, TILE[2] * k, TILE[3] * k],
        radius=TILE_R * k, fill=255)
    out = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    out.paste(gradient_image(N, GRAD, 45), (0, 0), round_mask)
    out.paste(Image.new("RGBA", (N, N), BG_LIGHT + (255,)), (0, 0), mask)
    return out.resize((s, s), Image.LANCZOS)


DOT_ROWS = [
    "X...X",
    "XX..X",
    "X.X.X",
    "X..XX",
    "X...X",
]


def render_dot(s):
    sp = spec(s)
    N, k = s * SS, s * SS / float(UNIT)
    x0, yt, x1, yb = sp["box"]
    rows, cols = len(DOT_ROWS), len(DOT_ROWS[0])
    px_ = (x1 - x0) / (cols - 1.0)
    py_ = (yb - yt) / (rows - 1.0)
    side = min(px_, py_) * (0.80 if s > 32 else 0.90)
    mask = Image.new("L", (N, N), 0)
    dm = ImageDraw.Draw(mask)
    r = side / 2.0 * k
    for j, row in enumerate(DOT_ROWS):
        for i, ch in enumerate(row):
            if ch != "X":
                continue
            cx, cy = (x0 + i * px_) * k, (yt + j * py_) * k
            dm.rounded_rectangle([cx - r, cy - r, cx + r, cy + r],
                                 radius=r * 0.30, fill=255)
    img = paint_mask(tile_layer(N, k), mask, gradient_image(N, GRAD, 0))
    return img.resize((s, s), Image.LANCZOS)


VARIANTS = {
    "solid": render_solid,
    "seam": render_seam,
    "carved": render_carved,
    "dot": render_dot,
}


# ---------------------------------------------------------------- 输出

def write_ico(path, frames):
    import io
    blobs = []
    for size, img in frames:
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        blobs.append((size, bio.getvalue()))
    n = len(blobs)
    head = struct.pack("<HHH", 0, 1, n)
    off = 6 + 16 * n
    dirs, data = b"", b""
    for size, png in blobs:
        dirs += struct.pack("<BBBBHHII",
                            0 if size >= 256 else size, 0 if size >= 256 else size,
                            0, 0, 1, 32, len(png), off + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(head + dirs + data)


def preview_sheet(name, variants):
    pad, gap = 22, 26
    cell = 256 + 2 * pad
    sub = [48, 32, 24, 16]
    sub_w = sum(sub) + 8 * (len(sub) - 1)
    width = pad + len(variants) * (cell + gap)
    row_h = cell + 40 + 46
    sheet = Image.new("RGBA", (width, row_h * 2 + 40), (255, 255, 255, 255))
    font = ImageFont.load_default()
    d = ImageDraw.Draw(sheet)
    for row, bg in enumerate([(255, 255, 255), (32, 36, 46)]):
        y_base = 40 + row * row_h
        d.rectangle([0, y_base, width, y_base + row_h - 1], fill=bg + (255,))
        for col, v in enumerate(variants):
            x = pad + col * (cell + gap)
            big = VARIANTS[v](256)
            sheet.paste(big, (x + pad, y_base + pad), big)
            d.text((x + pad, y_base + pad + 256 + 4), v,
                   fill=(120, 120, 120, 255) if bg[0] > 128 else (210, 210, 210, 255),
                   font=font)
            sx = x + pad + (256 - sub_w) // 2
            sy = y_base + pad + 256 + 20
            for s in sub:
                im = VARIANTS[v](s)
                sheet.paste(im, (sx, sy + (48 - s) // 2), im)
                sx += s + 8
    sheet.convert("RGB").save(os.path.join(OUT, name))
    print("preview ->", os.path.join(OUT, name))


def zoom_sheet(name, variants):
    """把小尺寸放大（NEAREST）看清真实像素，这才是图标成败的地方。"""
    zoom = 9
    small = [16, 24, 32]
    band_w = max(small) * zoom + 16
    cell_w = 2 * band_w + 8 + 28
    width = 28 + len(variants) * cell_w
    row_h = max(small) * zoom + 16 + 26
    height = 34 + len(small) * row_h
    sheet = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for col, v in enumerate(variants):
        x0 = 28 + col * cell_w
        d.text((x0, 10), v, fill=(60, 60, 60, 255), font=font)
        for i, s in enumerate(small):
            y0 = 34 + i * row_h + (max(small) - s) * zoom // 2
            for row, bg in enumerate([(255, 255, 255), (32, 36, 46)]):
                band = Image.new("RGBA", (s * zoom + 16, s * zoom + 16), bg + (255,))
                im = VARIANTS[v](s).resize((s * zoom, s * zoom), Image.NEAREST)
                band.paste(im, (8, 8), im)
                sheet.paste(band, (x0 + row * (band_w + 8), y0))
    sheet.convert("RGB").save(os.path.join(OUT, name))
    print("zoom    ->", os.path.join(OUT, name))


def main():
    os.makedirs(OUT, exist_ok=True)
    for v in VARIANTS:
        VARIANTS[v](256).save(os.path.join(OUT, "%s-256.png" % v))
    preview_sheet("candidates.png", list(VARIANTS))
    zoom_sheet("zoom-small.png", list(VARIANTS))

    if "--ico" in sys.argv:
        v = sys.argv[sys.argv.index("--ico") + 1]
        frames = [(s, VARIANTS[v](s)) for s in SIZES]
        dst = os.path.join(OUT, "mdwright-%s.ico" % v)
        write_ico(dst, frames)
        print("ico ->", dst, "frames", SIZES)


if __name__ == "__main__":
    main()
