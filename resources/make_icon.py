"""Generate a Biofeedback app icon (Windows .ico): red heart with white
ECG line through it.

Produces: resources/icon.ico

Replace resources/icon.ico with your own .ico to use a custom icon.
To convert a PNG to .ico via Pillow:
    from PIL import Image
    Image.open('your.png').save('icon.ico',
        sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
"""
import math
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow is required. Install with:  pip install pillow")
    sys.exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))


def heart_polygon(cx: float, cy: float, size: float, n: int = 240):
    pts = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t)
              - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * size / 17.0, cy + y * size / 17.0))
    return pts


def render_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = size / 2
    cy = size / 2

    heart_size = size * 0.46
    pts = heart_polygon(cx, cy + size * 0.04, heart_size)
    draw.polygon(pts, fill=(225, 35, 45, 255))

    line_y = cy + size * 0.06
    line_w = size * 0.78
    line_l = cx - line_w / 2
    n_points = 220
    line_pts = []
    line_thickness = max(2, int(size / 36))
    for i in range(n_points):
        t = i / (n_points - 1)
        x = line_l + t * line_w
        y_off = 0.0
        if 0.36 <= t <= 0.42:
            y_off = -size * 0.03 * math.sin((t - 0.36) / 0.06 * math.pi)
        elif 0.42 <= t <= 0.46:
            y_off = size * 0.04 * (t - 0.42) / 0.04
        elif 0.46 <= t <= 0.50:
            y_off = -size * 0.18 * (t - 0.46) / 0.04
        elif 0.50 <= t <= 0.54:
            y_off = -size * 0.18 * (1 - (t - 0.50) / 0.04)
        elif 0.54 <= t <= 0.58:
            y_off = size * 0.08 * (1 - abs(t - 0.56) / 0.02)
        elif 0.62 <= t <= 0.74:
            y_off = -size * 0.05 * math.sin((t - 0.62) / 0.12 * math.pi)
        line_pts.append((x, line_y + y_off))

    draw.line(line_pts, fill=(255, 255, 255, 255), width=line_thickness, joint="curve")
    return img


def main() -> None:
    ico_path = os.path.join(HERE, "icon.ico")
    # Render a high-res master, then let Pillow downsample to all standard
    # Windows icon sizes inside one multi-resolution .ico file.
    master = render_icon(256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256)]
    master.save(ico_path, format="ICO", sizes=sizes)
    print(f"Created {ico_path}")


if __name__ == "__main__":
    main()
