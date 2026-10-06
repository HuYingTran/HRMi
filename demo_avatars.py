"""Vẽ avatar hoạt hình con vật (phong cách phẳng) cho dữ liệu mô phỏng.

Chỉ dùng Pillow, không cần tải ảnh nào. Vẽ trên canvas 1024px rồi thu nhỏ
khi lưu để nét được mịn.

    python demo_avatars.py   # xuất bảng xem trước demo_avatars.png
"""
from PIL import Image, ImageDraw

S = 1024
INK = (45, 35, 40)
WHITE = (255, 255, 255)
BLUSH = (255, 150, 160)

BACKGROUNDS = [
    (186, 225, 255), (255, 214, 165), (202, 240, 198), (255, 198, 214), (221, 205, 255),
    (255, 236, 160), (176, 232, 226), (255, 205, 190), (210, 225, 180), (200, 215, 245),
]


def _e(d, cx, cy, rx, ry=None, fill=None):
    ry = rx if ry is None else ry
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=fill)


def _eyes(d, y, dx, r, cx=512):
    for x in (cx - dx, cx + dx):
        _e(d, x, y, r, r * 1.12, INK)
        _e(d, x - r * 0.32, y - r * 0.38, r * 0.34, fill=WHITE)


def _cheeks(d, y, dx, color=BLUSH, r=42):
    for x in (512 - dx, 512 + dx):
        _e(d, x, y, r, r * 0.62, color)


def _smile(d, cx, y, w, color=INK, width=12):
    """Miệng hình chữ ω."""
    d.arc((cx - w, y - w * 0.6, cx, y + w * 0.6), 10, 170, fill=color, width=width)
    d.arc((cx, y - w * 0.6, cx + w, y + w * 0.6), 10, 170, fill=color, width=width)


def cat(d):
    fur, inner = (255, 170, 90), (255, 200, 205)
    for sx in (1, -1):
        ear = [(512 - sx * 262, 430), (512 - sx * 220, 140), (512 - sx * 50, 330)]
        d.polygon(ear, fill=fur)
        d.polygon([(512 - sx * 230, 390), (512 - sx * 212, 215), (512 - sx * 100, 330)], fill=inner)
    _e(d, 512, 590, 340, 300, fur)
    for i, w in enumerate((70, 50, 70)):  # vằn trên trán
        x = 452 + i * 60
        d.polygon([(x - 18, 300), (x + 18, 300), (x, 300 + w + 40)], fill=(225, 130, 60))
    _cheeks(d, 670, 200)
    _eyes(d, 560, 120, 40)
    d.polygon([(486, 640), (538, 640), (512, 672)], fill=(240, 110, 130))
    _smile(d, 512, 680, 46)
    for sx in (1, -1):
        for dy in (-18, 22):
            d.line([(512 - sx * 300, 660 + dy * 2), (512 - sx * 430, 640 + dy * 4)], fill=INK, width=8)


def dog(d):
    fur, ear, muzzle = (214, 160, 110), (130, 85, 55), (250, 232, 210)
    _e(d, 512, 580, 310, 300, fur)
    for sx in (1, -1):
        d.ellipse((512 - sx * 330 - 95, 330, 512 - sx * 330 + 95, 720), fill=ear)
    _e(d, 610, 470, 95, 85, (190, 135, 90))  # đốm quanh mắt
    _e(d, 512, 700, 170, 125, muzzle)
    _e(d, 512, 790, 34, 48, (240, 100, 120))  # lưỡi
    _e(d, 512, 650, 62, 44, INK)
    _e(d, 494, 636, 18, 10, (120, 110, 120))
    _smile(d, 512, 725, 52)
    _eyes(d, 530, 110, 38)
    _cheeks(d, 690, 220)


def pig(d):
    skin, dark = (255, 182, 193), (240, 130, 150)
    for sx in (1, -1):
        d.polygon([(512 - sx * 270, 380), (512 - sx * 300, 170), (512 - sx * 120, 300)], fill=dark)
    _e(d, 512, 590, 345, 305, skin)
    _cheeks(d, 690, 230, (255, 140, 160))
    _e(d, 512, 670, 130, 92, dark)
    for x in (468, 556):
        _e(d, x, 670, 20, 34, (170, 70, 95))
    _eyes(d, 520, 125, 36)
    d.arc((462, 730, 562, 800), 20, 160, fill=INK, width=12)


def chicken(d):
    body, red, beak = (255, 248, 225), (235, 60, 60), (255, 160, 40)
    for x, y, r in ((440, 270, 62), (512, 235, 75), (584, 270, 62)):
        _e(d, x, y, r, fill=red)
    _e(d, 512, 590, 320, 310, body)
    _cheeks(d, 640, 200, (255, 170, 170))
    _eyes(d, 530, 105, 38)
    d.polygon([(440, 600), (584, 600), (512, 700)], fill=beak)
    d.polygon([(440, 600), (584, 600), (512, 630)], fill=(255, 190, 80))
    _e(d, 512, 740, 32, 52, red)


def fish(d):
    body, belly, fin = (255, 140, 60), (255, 200, 120), (240, 100, 40)
    d.polygon([(700, 540), (930, 360), (880, 540), (930, 720)], fill=fin)
    d.polygon([(360, 380), (520, 230), (640, 380)], fill=fin)
    _e(d, 470, 540, 320, 215, body)
    _e(d, 450, 620, 230, 100, belly)
    for x in (560, 640):
        d.arc((x - 60, 360, x + 60, 720), 300, 60, fill=WHITE, width=16)
    _e(d, 300, 500, 62, fill=WHITE)
    _e(d, 310, 505, 34, fill=INK)
    _e(d, 298, 492, 12, fill=WHITE)
    d.arc((150, 530, 230, 610), 300, 60, fill=INK, width=12)
    for x, y, r in ((160, 290, 34), (230, 200, 22), (130, 170, 16)):
        d.ellipse((x - r, y - r, x + r, y + r), outline=WHITE, width=8)


def rabbit(d):
    fur, inner = (245, 245, 250), (255, 190, 200)
    for cx in (420, 604):
        d.ellipse((cx - 70, 60, cx + 70, 470), fill=fur)
        d.ellipse((cx - 36, 110, cx + 36, 430), fill=inner)
    _e(d, 512, 610, 310, 280, fur)
    _cheeks(d, 690, 190)
    _eyes(d, 580, 105, 36)
    _e(d, 512, 660, 30, 22, (240, 120, 140))
    d.rectangle((488, 705, 536, 765), fill=WHITE, outline=(200, 200, 210), width=6)
    d.line([(512, 705), (512, 765)], fill=(200, 200, 210), width=5)
    _smile(d, 512, 690, 40)


def bear(d):
    fur, light = (160, 110, 75), (230, 195, 160)
    for x in (300, 724):
        _e(d, x, 320, 105, fill=fur)
        _e(d, x, 320, 58, fill=light)
    _e(d, 512, 600, 325, 300, fur)
    _e(d, 512, 700, 150, 115, light)
    _e(d, 512, 655, 52, 36, INK)
    _smile(d, 512, 715, 44)
    _eyes(d, 555, 115, 34)
    _cheeks(d, 670, 230, (240, 140, 120))


def panda(d):
    for x in (290, 734):
        _e(d, x, 300, 105, fill=INK)
    _e(d, 512, 590, 330, 300, WHITE)
    for sx in (1, -1):
        cx = 512 - sx * 115
        d.ellipse((cx - 78, 470, cx + 78, 650), fill=INK)
        _e(d, cx, 545, 30, fill=WHITE)
        _e(d, cx + 4, 550, 16, fill=INK)
    _e(d, 512, 670, 44, 30, INK)
    _smile(d, 512, 725, 40)
    _cheeks(d, 700, 220)


def frog(d):
    skin, dark = (120, 200, 90), (80, 160, 60)
    for x in (360, 664):
        _e(d, x, 330, 115, fill=skin)
    _e(d, 512, 610, 370, 270, skin)
    _e(d, 512, 700, 300, 150, (160, 225, 120))
    for x in (360, 664):
        _e(d, x, 320, 72, fill=WHITE)
        _e(d, x + 8, 330, 38, fill=INK)
        _e(d, x - 4, 316, 12, fill=WHITE)
    for x in (480, 544):
        _e(d, x, 540, 10, fill=dark)
    d.arc((330, 520, 694, 760), 25, 155, fill=INK, width=14)
    _cheeks(d, 640, 270, (255, 160, 150), 46)


def fox(d):
    fur, dark, white = (245, 130, 50), (120, 60, 30), (255, 245, 235)
    for sx in (1, -1):
        d.polygon([(512 - sx * 300, 450), (512 - sx * 260, 110), (512 - sx * 60, 330)], fill=fur)
        d.polygon([(512 - sx * 255, 400), (512 - sx * 245, 210), (512 - sx * 130, 330)], fill=dark)
    _e(d, 512, 580, 340, 280, fur)
    d.polygon([(190, 600), (512, 860), (834, 600), (700, 640), (512, 700), (324, 640)], fill=white)
    _e(d, 512, 740, 160, 120, white)
    _e(d, 512, 650, 44, 32, INK)
    _smile(d, 512, 700, 38)
    _eyes(d, 540, 125, 34)


def cow(d):
    white, spot, pink = (255, 255, 252), INK, (255, 190, 195)
    for sx in (1, -1):
        d.polygon([(512 - sx * 210, 330), (512 - sx * 260, 170), (512 - sx * 150, 300)], fill=(250, 230, 180))
        d.ellipse((512 - sx * 330 - 100, 370, 512 - sx * 330 + 100, 470), fill=white)
    _e(d, 512, 570, 300, 300, white)
    _e(d, 390, 420, 95, 70, spot)
    _e(d, 690, 400, 62, 58, spot)
    _e(d, 512, 750, 220, 125, pink)
    for x in (445, 579):
        _e(d, x, 745, 24, 34, (210, 110, 120))
    _eyes(d, 575, 120, 34)
    d.arc((462, 790, 562, 850), 20, 160, fill=INK, width=10)


ANIMALS = [
    ("cho", dog), ("meo", cat), ("lon", pig), ("ga", chicken), ("ca", fish), ("tho", rabbit),
    ("gau", bear), ("gau-truc", panda), ("ech", frog), ("cao", fox), ("bo", cow),
]


def animal_avatar(index):
    """Ảnh thứ `index`: lần lượt từng con vật, đổi màu nền theo index."""
    name, painter = ANIMALS[index % len(ANIMALS)]
    img = Image.new("RGB", (S, S), BACKGROUNDS[index % len(BACKGROUNDS)])
    painter(ImageDraw.Draw(img))
    return name, img


if __name__ == "__main__":
    cell = 220
    sheet = Image.new("RGB", (cell * 6, cell * 2), (20, 24, 32))
    for i in range(len(ANIMALS)):
        _, img = animal_avatar(i)
        sheet.paste(img.resize((cell - 20, cell - 20), Image.LANCZOS), ((i % 6) * cell + 10, (i // 6) * cell + 10))
    sheet.save("demo_avatars.png")
    print("Đã lưu demo_avatars.png")
