"""앱 아이콘/스플래시를 만듭니다 (PIL)."""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent.parent
ASSETS = HERE / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

BG_TOP = (36, 58, 96)
BG_BOT = (18, 22, 29)
ACCENT = (111, 178, 255)
NOTE = (255, 255, 255)


def gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), top)
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        d.line([(0, y), (size, y)],
               fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def draw_note(d, cx, cy, scale):
    """简易음표(♪) 그리기."""
    r = int(28 * scale)
    # 음표 머리 (기울어진 타원)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=NOTE)
    # 기둥
    stem_w = int(9 * scale)
    d.rectangle([cx + r - stem_w, cy - int(150 * scale), cx + r, cy], fill=NOTE)
    # 깃발
    flag = [(cx + r, cy - int(150 * scale)),
            (cx + r + int(74 * scale), cy - int(112 * scale)),
            (cx + r + int(70 * scale), cy - int(80 * scale)),
            (cx + r, cy - int(104 * scale))]
    d.polygon(flag, fill=NOTE)


def make_icon(size=512):
    img = gradient(size, BG_TOP, BG_BOT).convert("RGBA")
    d = ImageDraw.Draw(img)
    # 살짝 둥근 모서리 마스크
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(size * 0.22), fill=255)
    img.putalpha(mask)
    draw_note(d, int(size * 0.40), int(size * 0.66), size / 512.0)
    return img


def make_presplash(w=720, h=1280):
    img = gradient(h, BG_TOP, BG_BOT).convert("RGBA")
    # 정사각형 영역에 아이콘 배치
    side = int(w * 0.42)
    icon = make_icon(side)
    img.paste(icon, ((w - side) // 2, (h - side) // 2), icon)
    return img


if __name__ == "__main__":
    icon = make_icon()
    icon.save(ASSETS / "icon.png", optimize=True)
    # 적응형 아이콘용前景/배경
    fg = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)
    draw_note(d, int(512 * 0.40), int(512 * 0.60), 0.78)
    fg.save(ASSETS / "icon_fg.png", optimize=True)
    Image.new("RGBA", (512, 512), BG_TOP + (255,)).save(ASSETS / "icon_bg.png", optimize=True)

    sp = make_presplash()
    sp.save(ASSETS / "presplash.png", optimize=True)
    for p in ("icon.png", "icon_fg.png", "icon_bg.png", "presplash.png"):
        print(p, (ASSETS / p).stat().st_size, "bytes")
