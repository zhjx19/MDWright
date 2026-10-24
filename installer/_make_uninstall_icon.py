# SPDX-License-Identifier: AGPL-3.0-or-later
# Generate uninstall-mdwright.ico: source mdwright.ico pixel art with a red X
# badge overlaid at the bottom-right corner. Pure stdlib (no PIL):
# reads 32bpp BMP frames from the source .ico, composes pixel-style X,
# writes new .ico with frames at source sizes (nearest-neighbour scale).
#
# Usage: python _make_uninstall_icon.py [src.ico] [dst.ico]
import os
import struct
import sys
import zlib


def read_ico(path):
    with open(path, "rb") as f:
        data = f.read()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    frames = []
    for i in range(count):
        off = 6 + 16 * i
        w, h, colors, res, planes, bpp, size, offset = struct.unpack("<BBBBHHII", data[off:off + 16])
        raw = data[offset:offset + size]
        frames.append({"w": w or 256, "h": h or 256, "bpp": bpp, "raw": raw, "size": size})
    return frames


# ---------- PNG decode/encode (stdlib only, RGBA 8-bit) ----------

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def png_decode(raw):
    """Decode a PNG file (truecolor 8-bit RGB/RGBA) to (w, h, rows of (r,g,b,a))."""
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "not a png"
    pos = 8
    idat = bytearray()
    meta = {}
    while pos < len(raw):
        ln = struct.unpack(">I", raw[pos:pos + 4])[0]
        ctype = raw[pos + 4:pos + 8]
        chunk = raw[pos + 8:pos + 8 + ln]
        if ctype == b"IHDR":
            w, h, depth, color, comp, filt, interlace = struct.unpack(">IIBBBBB", chunk)
            meta = {"w": w, "h": h, "depth": depth, "color": color, "interlace": interlace}
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + ln
    w, h, color = meta["w"], meta["h"], meta["color"]
    assert meta["depth"] == 8 and color in (2, 6) and meta["interlace"] == 0, "png layout unsupported: %s" % meta
    bpp = 4 if color == 6 else 3
    data = zlib.decompress(bytes(idat))
    stride = w * bpp
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        ftype = data[pos]
        pos += 1
        line = bytearray(data[pos:pos + stride])
        pos += stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + (left + prev[i]) // 2) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                ul = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], ul)) & 0xFF
        out += line
        prev = line
    px = []
    for y in range(h):
        row = []
        base = y * stride
        for x in range(w):
            if bpp == 4:
                r, g, b, a = out[base + x * 4: base + x * 4 + 4]
            else:
                r, g, b = out[base + x * 3: base + x * 3 + 3]
                a = 255
            row.append((r, g, b, a))
        px.append(row)
    return px


def png_encode(px):
    h = len(px)
    w = len(px[0])
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter 0
        for x in range(w):
            r, g, b, a = px[y][x]
            raw += bytes((r, g, b, a))

    def chunk(ctype, payload):
        c = struct.pack(">I", len(payload)) + ctype + payload
        return c + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def decode_frame(fr):
    raw = fr["raw"]
    if raw[:4] == b"\x89PNG":
        return png_decode(raw)
    return decode_bmp_frame(fr)


def decode_bmp_frame(fr):
    """Decode a 32bpp DIB frame to top-down rows of (r,g,b,a)."""
    w, h = fr["w"], fr["h"]
    raw = fr["raw"]
    hdr = struct.unpack("<IiiHHIIiiII", raw[:40])
    hbpp = hdr[5]
    if hbpp != 32:
        raise ValueError("frame bpp %d not supported" % hbpp)
    xor = raw[40:40 + w * h * 4]
    and_stride = ((w + 31) // 32) * 4
    and_size = and_stride * h
    and_mask = raw[40 + w * h * 4: 40 + w * h * 4 + and_size]
    px = []  # top-down rows of (r,g,b,a)
    for y in range(h):
        sy = h - 1 - y  # bottom-up
        row = []
        for x in range(w):
            b, g, r, a = xor[(sy * w + x) * 4:(sy * w + x) * 4 + 4]
            row.append((r, g, b, a))
        px.append(row)
    # apply AND mask (transparency for 0 alpha entries)
    for y in range(h):
        for x in range(w):
            byte = and_mask[y * and_stride + x // 8]
            if not (byte >> (7 - x % 8)) & 1:
                r, g, b, a = px[y][x]
                px[y][x] = (r, g, b, 0) if a == 0 else (r, g, b, a)
    return px


def encode_bmp_frame(px):
    """Encode top-down RGBA rows back to a 32bpp DIB frame (bottom-up BGRA + AND mask)."""
    h = len(px)
    w = len(px[0])
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[y][x]
            xor += bytes((b, g, r, a))
    and_stride = ((w + 31) // 32) * 4
    and_mask = bytearray(and_stride * h)
    for y in range(h):
        for x in range(w):
            if px[y][x][3] == 0:
                and_mask[y * and_stride + x // 8] |= 1 << (7 - x % 8)
    bih = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0)
    return bih + bytes(xor) + bytes(and_mask)


def scale_nearest(px, tw, th):
    sh, sw = len(px), len(px[0])
    return [[px[y * sh // th][x * sw // tw] for x in range(tw)] for y in range(th)]


def draw_x_badge(px):
    """Pixel-style red X in a white badge at the bottom-right corner."""
    h = len(px)
    w = len(px[0])
    s = max(w, h)
    badge = max(6, int(s * 0.46))
    x0 = w - badge
    y0 = h - badge
    # badge: opaque white rounded block (corner pixels cut) + dark border
    border = max(1, s // 48)
    for y in range(badge):
        for x in range(badge):
            gx, gy = x0 + x, y0 + y
            cut_corner = (x + y < border * 3) or ((badge - 1 - x) + (badge - 1 - y) < border * 3)
            if cut_corner:
                continue
            edge = (x < border or y < border or x >= badge - border or y >= badge - border)
            px[gy][gx] = (40, 40, 40, 255) if edge else (255, 255, 255, 255)
    # X arms: two diagonals, thickness ~ badge/4, dark outline + red core
    t = max(2, badge // 4)
    core = (200, 30, 30, 255)
    dark = (40, 40, 40, 255)
    for y in range(badge):
        for x in range(badge):
            gx, gy = x0 + x, y0 + y
            if px[gy][gx][3] == 0:
                continue
            d1 = abs(x - y)          # diagonal TL->BR
            d2 = abs(x - (badge - 1 - y))  # diagonal TR->BL
            on = d1 < t or d2 < t
            if not on:
                continue
            near_edge = d1 < t or d2 < t
            outline = (d1 < t and (x <= border or y <= border or x >= badge - 1 - border or y >= badge - 1 - border)) or \
                      (d2 < t and (x <= border or y <= border or x >= badge - 1 - border or y >= badge - 1 - border))
            px[gy][gx] = dark if outline else core
    return px


def build_ico(frames):
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(frames))
    body = bytearray()
    offset = 6 + 16 * len(frames)
    entries = []
    for w, h, raw in frames:
        entries.append((w, h, len(raw), offset))
        body += raw
        offset += len(raw)
    for w, h, size, off in entries:
        out += struct.pack("<BBBBHHII", w if w < 256 else 0, h if h < 256 else 0, 0, 0, 1, 32, size, off)
    out += body
    return bytes(out)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "mdwright.ico"
    dst = sys.argv[2] if len(sys.argv) > 2 else "uninstall-mdwright.ico"
    frames = read_ico(src)
    print("源帧:", [(f["w"], f["h"], f["bpp"]) for f in frames])
    out_frames = []
    for fr in frames:
        try:
            px = decode_frame(fr)
        except (ValueError, AssertionError) as e:
            print("  跳过帧", fr["w"], "x", fr["h"], ":", e)
            continue
        px = draw_x_badge(px)
        out_frames.append((fr["w"], fr["h"], png_encode(px)))
        print("  合成帧", fr["w"], "x", fr["h"], "OK")
    with open(dst, "wb") as f:
        f.write(build_ico(out_frames))
    print("写出:", dst, os.path.getsize(dst), "bytes,", len(out_frames), "帧")


if __name__ == "__main__":
    main()
