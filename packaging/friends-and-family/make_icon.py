"""Draws the MLX-Audio app icon (1024x1024 PNG) with numpy + zlib only - no image libraries needed."""
import struct, sys, zlib
import numpy as np

S = 1024
SS = 3                      # supersampling for smooth edges
N = S * SS
y, x = np.mgrid[0:N, 0:N].astype(np.float32)
x /= SS; y /= SS

def rrect_sdf(px, py, cx, cy, hw, hh, r):
    qx = np.abs(px - cx) - (hw - r)
    qy = np.abs(py - cy) - (hh - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r

# macOS-style squircle-ish tile with margin (icon grid: ~100px transparent margin at 1024)
tile = rrect_sdf(x, y, 512, 512, 412, 412, 185)
alpha = np.clip(0.5 - tile, 0, 1)

# background gradient: deep indigo (top) -> electric violet/blue (bottom)
t = np.clip((y - 100) / 824, 0, 1)[..., None]
top = np.array([46, 30, 120], np.float32)
bot = np.array([98, 84, 245], np.float32)
rgb = top * (1 - t) + bot * t
# soft light bloom in upper-left
glow = np.exp(-(((x - 330) ** 2 + (y - 260) ** 2) / (2 * 260 ** 2)))[..., None]
rgb = rgb + glow * np.array([40, 46, 70], np.float32)

# waveform: 7 rounded bars
heights = [150, 300, 470, 620, 470, 300, 150]
bar_w, gap = 62, 40
total = len(heights) * bar_w + (len(heights) - 1) * gap
x0 = 512 - total / 2 + bar_w / 2
bars = np.zeros((N, N), np.float32)
for i, h in enumerate(heights):
    cx = x0 + i * (bar_w + gap)
    d = rrect_sdf(x, y, cx, 512, bar_w / 2, h / 2, bar_w / 2)
    bars = np.maximum(bars, np.clip(0.5 - d, 0, 1))
# subtle drop shadow under bars
shadow = np.zeros((N, N), np.float32)
for i, h in enumerate(heights):
    cx = x0 + i * (bar_w + gap)
    d = rrect_sdf(x, y - 14, cx, 512, bar_w / 2, h / 2, bar_w / 2)
    shadow = np.maximum(shadow, np.exp(-np.maximum(d, 0) ** 2 / (2 * 16 ** 2)) * (d < 40))
rgb = rgb * (1 - 0.30 * shadow[..., None] * (1 - bars[..., None]))
white = np.array([255, 255, 255], np.float32)
# bars: white fading to a pale lavender toward the bottom for depth
bar_col = white * (1 - 0.10 * t) + np.array([210, 205, 255], np.float32) * (0.10 * t)
rgb = rgb * (1 - bars[..., None]) + bar_col * bars[..., None]

# thin inner highlight along the top edge of the tile
edge = np.clip(1 - np.abs(tile + 3) / 3, 0, 1) * np.clip((330 - y) / 330, 0, 1)
rgb = rgb + edge[..., None] * 35

rgb = np.clip(rgb, 0, 255)
rgba = np.dstack([rgb, alpha * 255])
# downsample
rgba = rgba.reshape(S, SS, S, SS, 4).mean(axis=(1, 3))
# premultiply-safe colour bleed is not needed for PNG straight alpha
out = np.clip(rgba, 0, 255).astype(np.uint8)

def png(path, a):
    h, w, _ = a.shape
    raw = b"".join(b"\x00" + a[r].tobytes() for r in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

png(sys.argv[1], out)
print("wrote", sys.argv[1])
