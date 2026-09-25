"""Render the README demo of Picture Index indexing a folder and searching the grid."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "web" / "logo.png"
OUT = ROOT / "docs" / "demo.gif"

W, H = 960, 540
SCALE = 2
BG = (247, 247, 248)
SURFACE = (255, 255, 255)
SIDE = (243, 244, 246)
BORDER = (226, 228, 232)
TEXT = (32, 33, 36)
MUTED = (138, 144, 153)
ACCENT = (53, 104, 168)
SELECTED = (234, 242, 252)
INK = (29, 63, 115)
CREAM = (245, 236, 214)
GOLD = (196, 154, 58)
BLUE = (126, 168, 214)

PHOTOS = [
    ("IMG_2041.jpg", "sky", False),
    ("garden.jpg", "garden", False),
    ("paint-bucket.jpg", "paint", True),
    ("sunset.jpg", "sunset", False),
    ("night.jpg", "night", False),
    ("beach.jpg", "beach", False),
    ("kitchen.jpg", "kitchen", False),
    ("street.jpg", "street", False),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size * SCALE)


def blend(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(channel + (BG[i] - channel) * (1 - amount)) for i, channel in enumerate(color))


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius * SCALE, fill=fill)


def scene(draw: ImageDraw.ImageDraw, kind: str, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if kind == "sky":
        rounded(draw, box, 6, (142, 190, 220))
        draw.ellipse((x0 + w * 0.62, y0 + h * 0.16, x0 + w * 0.86, y0 + h * 0.42), fill=(255, 214, 120))
    elif kind == "garden":
        rounded(draw, box, 6, (186, 214, 168))
        draw.polygon(
            [(x0, y1), (x0 + w * 0.45, y0 + h * 0.42), (x0 + w, y1)],
            fill=(92, 140, 86),
        )
    elif kind == "paint":
        rounded(draw, box, 6, (232, 236, 242))
        gap = w * 0.08
        left = (x0 + gap, y0 + h * 0.28, x0 + w * 0.48, y0 + h * 0.86)
        right = (x0 + w * 0.52, y0 + h * 0.22, x1 - gap, y0 + h * 0.86)
        draw.rounded_rectangle(left, radius=8 * SCALE, fill=CREAM)
        draw.rounded_rectangle(right, radius=8 * SCALE, fill=BLUE)
        tab = (right[2] - w * 0.22, right[1] - h * 0.08, right[2] - w * 0.04, right[1] + h * 0.08)
        draw.rounded_rectangle(tab, radius=3 * SCALE, fill=GOLD)
    elif kind == "sunset":
        rounded(draw, box, 6, (242, 156, 92))
        draw.rectangle((x0, y0 + h * 0.62, x1, y1), fill=(120, 78, 92))
        draw.ellipse((x0 + w * 0.38, y0 + h * 0.28, x0 + w * 0.68, y0 + h * 0.62), fill=(255, 214, 140))
    elif kind == "night":
        rounded(draw, box, 6, (28, 42, 74))
        for px, py, r in ((0.25, 0.3, 2), (0.55, 0.22, 1.5), (0.72, 0.4, 1.4), (0.4, 0.48, 1.2)):
            draw.ellipse(
                (x0 + w * px, y0 + h * py, x0 + w * px + r * SCALE * 2, y0 + h * py + r * SCALE * 2),
                fill=(255, 244, 214),
            )
    elif kind == "beach":
        rounded(draw, box, 6, (244, 214, 168))
        draw.rectangle((x0, y0, x1, y0 + h * 0.46), fill=(120, 186, 214))
    elif kind == "kitchen":
        rounded(draw, box, 6, (214, 206, 196))
        draw.rounded_rectangle(
            (x0 + w * 0.18, y0 + h * 0.22, x0 + w * 0.82, y0 + h * 0.78),
            radius=4 * SCALE,
            fill=(255, 250, 245),
        )
    else:
        rounded(draw, box, 6, (168, 176, 186))
        draw.rectangle((x0, y0 + h * 0.55, x1, y1), fill=(90, 98, 108))
        draw.rectangle((x0 + w * 0.2, y0 + h * 0.28, x0 + w * 0.38, y1), fill=(70, 78, 88))


def frame(step: int, logo: Image.Image) -> Image.Image:
    image = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    draw = ImageDraw.Draw(image)
    title = font(16, True)
    body = font(13)
    small = font(11)
    tiny = font(10)

    win = (28 * SCALE, 24 * SCALE, (W - 28) * SCALE, (H - 24) * SCALE)
    rounded(draw, win, 10, SURFACE)
    draw.rounded_rectangle(win, radius=10 * SCALE, outline=BORDER, width=SCALE)

    logo_box = logo.resize((28 * SCALE, 28 * SCALE), Image.Resampling.LANCZOS)
    image.paste(logo_box, (44 * SCALE, 40 * SCALE), logo_box.convert("RGBA"))
    draw.text((80 * SCALE, 44 * SCALE), "Picture Index", font=title, fill=TEXT)

    path_box = (230 * SCALE, 38 * SCALE, 690 * SCALE, 70 * SCALE)
    rounded(draw, path_box, 5, (255, 255, 255))
    draw.rounded_rectangle(path_box, radius=5 * SCALE, outline=BORDER, width=SCALE)
    shown = "Pictures\\Phone"[: max(0, step - 2)]
    draw.text((242 * SCALE, 46 * SCALE), shown or "No folder selected", font=body, fill=TEXT if shown else MUTED)

    button = (706 * SCALE, 38 * SCALE, (W - 48) * SCALE, 70 * SCALE)
    pressed = 8 <= step < 11
    rounded(draw, button, 5, INK if pressed else ACCENT)
    label = "Index folder"
    lw = draw.textlength(label, font=body)
    draw.text((button[0] + (button[2] - button[0] - lw) / 2, 46 * SCALE), label, font=body, fill=(255, 255, 255))

    progress = min(1, max(0, (step - 8) / 10))
    if 8 <= step < 20:
        bar = (44 * SCALE, 82 * SCALE, (W - 48) * SCALE, 88 * SCALE)
        rounded(draw, bar, 2, BORDER)
        rounded(draw, (bar[0], bar[1], int(bar[0] + (bar[2] - bar[0]) * progress), bar[3]), 2, ACCENT)

    query = "paint"
    typed = query[: max(0, step - 28)]
    reveal = 0 if step < 36 else min(1, (step - 36) / 8)
    visible = []
    for name, kind, match in PHOTOS:
        if match or reveal < 1:
            visible.append((name, kind, match, 1 if match else 1 - reveal))
        elif match:
            visible.append((name, kind, match, 1))
    visible = [(n, k, m, a) for n, k, m, a in visible if a > 0.04]

    grid_left, grid_top = 44, 100
    card_w, card_h, gap = 148, 132, 12
    appear_from = 12
    for index, (name, kind, match) in enumerate(PHOTOS):
        born = appear_from + index * 2
        if step < born or (not match and reveal >= 1):
            continue
        col, row = (0, 0) if match and reveal > 0.85 else (index % 4, index // 4)
        pop = min(1, (step - born + 1) / 2)
        fade = 1 if match else max(0, 1 - reveal)
        x = (grid_left + col * (card_w + gap)) * SCALE
        y = (grid_top + row * (card_h + gap)) * SCALE
        cw, ch = int(card_w * SCALE * (0.92 + 0.08 * pop)), int(card_h * SCALE * (0.92 + 0.08 * pop))
        x += int((card_w * SCALE - cw) / 2)
        y += int((18 * SCALE) * (1 - pop))
        fill = blend(SELECTED if match and reveal > 0.2 else SURFACE, fade)
        outline = ACCENT if match and reveal > 0.4 else blend(BORDER, fade)
        draw.rounded_rectangle((x, y, x + cw, y + ch), radius=6 * SCALE, fill=fill, outline=outline, width=2 * SCALE if match and reveal > 0.4 else SCALE)
        pad = 8 * SCALE
        scene(draw, kind, (x + pad, y + pad, x + cw - pad, y + int(ch * 0.68)))
        draw.text((x + pad, y + int(ch * 0.74)), name, font=tiny, fill=blend(TEXT, fade))

    side = ((W - 28 - 250) * SCALE, 96 * SCALE, (W - 44) * SCALE, (H - 52) * SCALE)
    rounded(draw, side, 8, SIDE)
    draw.text((side[0] + 14 * SCALE, side[1] + 14 * SCALE), "Search", font=small, fill=MUTED)
    search = (side[0] + 14 * SCALE, side[1] + 34 * SCALE, side[2] - 14 * SCALE, side[1] + 66 * SCALE)
    rounded(draw, search, 5, SURFACE)
    draw.rounded_rectangle(search, radius=5 * SCALE, outline=ACCENT if typed else BORDER, width=SCALE)
    caret = "|" if typed and step % 4 < 2 else ""
    draw.text((search[0] + 10 * SCALE, search[1] + 6 * SCALE), (typed or "Filename or folder") + caret, font=body, fill=TEXT if typed else MUTED)

    if reveal > 0.35:
        preview = (side[0] + 14 * SCALE, side[1] + 86 * SCALE, side[2] - 14 * SCALE, side[1] + 210 * SCALE)
        scene(draw, "paint", preview)
        draw.text((side[0] + 14 * SCALE, side[1] + 222 * SCALE), "paint-bucket.jpg", font=font(13, True), fill=TEXT)
        draw.text((side[0] + 14 * SCALE, side[1] + 246 * SCALE), "Taken  2024-05-01", font=small, fill=MUTED)
        draw.text((side[0] + 14 * SCALE, side[1] + 266 * SCALE), "Folder  Pictures\\Phone", font=small, fill=MUTED)
    else:
        draw.text((side[0] + 14 * SCALE, side[1] + 96 * SCALE), "Select a photo.", font=body, fill=MUTED)

    count = "1 photo" if reveal > 0.8 else f"{min(8, max(0, (step - appear_from) // 2 + 1))} photos" if step >= appear_from else "0 photos"
    draw.text((44 * SCALE, (H - 44) * SCALE), count, font=small, fill=MUTED)
    return image.resize((W, H), Image.Resampling.LANCZOS)


def main() -> None:
    logo = Image.open(LOGO).convert("RGBA")
    frames = [frame(step, logo) for step in range(56)]
    palette = frames[40].quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    quantized = [item.quantize(palette=palette, dither=Image.Dither.NONE) for item in frames]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        OUT,
        save_all=True,
        append_images=quantized[1:],
        duration=90,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
