# -*- coding: utf-8 -*-
"""生成安装器 Hero 位图（中/英两张）+ 一键安装大按钮位图（常规/悬停）。

配色 = Neurova 应用品牌：深靛蓝渐变 #0A0E1F→#1A2148，主色 #4D6BFE。
产物落 NeurUI/src-tauri/nsis/assets/（.gitignore 之外，随包提交）。
"""
import os
import random

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "NeurUI", "src-tauri", "nsis", "assets")
os.makedirs(OUT, exist_ok=True)

W, H = 496, 150  # 紧凑 Hero：适配 MUI 原生窗口内容区（~360px 纵向预算）
TOP, BOT = (10, 14, 31), (26, 33, 72)
PRIMARY = (77, 107, 254)
TEXT_MAIN = (242, 245, 255)
TEXT_SUB = (174, 188, 245)


def _font(size, bold=False):
    for name in (["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_hero(lang: str) -> None:
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))

    # 星点
    rnd = random.Random(42)
    for _ in range(50):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        r = rnd.choice([1, 1])
        v = rnd.randint(50, 160)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(v, v, min(255, v + 30)))

    # 布局：左 Logo + 右两行文字（横向紧凑）
    logo = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "NeurUI", "public", "img", "neurova-icon.png")).convert("RGBA")
    lw = 96
    lh = int(logo.height * lw / logo.width)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    lx = 26
    img.paste(logo, (lx, (H - lh) // 2), logo)

    if lang == "zh":
        t1 = "Neurova 智星"
        t2 = "记忆 · 情感 · 自我进化的个人 AI 智能体"
        l1 = "开源 github.com/kingsa2026/Neurova · cnb.cool/kingsa2026/neurova"
        l2 = "官网 www.neurova.top"
    else:
        t1 = "Neurova"
        t2 = "Memory · Emotion · Self-Evolution — Personal AI Agent"
        l1 = "Open Source  github.com/kingsa2026/Neurova · cnb.cool/kingsa2026/neurova"
        l2 = "Website  www.neurova.top"
    tx = lx + lw + 18
    f1 = _font(24, bold=True)
    d.text((tx, 30), t1, font=f1, fill=TEXT_MAIN)
    f2 = _font(13)
    d.text((tx, 66), t2, font=f2, fill=TEXT_SUB)
    f3 = _font(12)
    d.text((tx, 90), l1, font=f3, fill=(150, 165, 220))
    d.text((tx, 110), l2, font=f3, fill=(150, 165, 220))

    img.save(os.path.join(OUT, f"hero_{lang}.bmp"))


def make_button() -> None:
    """一键安装大按钮位图（参考 Driver Booster 胶囊按钮）。

    BS_BITMAP 按钮 1:1 绘制无 9-slice：尺寸即最终显示像素（200x48 @96DPI），
    文字烙进图（双语并存，与语言选择器解耦）；背景纯白与底部白条一致。
    """
    BW, BH = 200, 48
    img = Image.new("RGB", (BW, BH), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, BW - 2, BH - 2], radius=BH // 2, fill=PRIMARY)
    text = "一键安装  Install"
    f = _font(18, bold=True)
    tw = d.textlength(text, font=f)
    d.text(((BW - tw) / 2, (BH - 22) / 2 - 2), text, font=f, fill=(255, 255, 255))
    img.save(os.path.join(OUT, "btn_install.bmp"))


def make_header() -> None:
    """MUI 头图 150x57：右侧品牌 Logo，背景与 MUI_BGCOLOR(1A2148) 无缝。

    直接落 nsis/ 根（tauri.conf headerImage 指向 ./nsis/header.bmp）。
    """
    W, H = 150, 57
    img = Image.new("RGB", (W, H), (26, 33, 72))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))
    logo = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "NeurUI", "public", "img", "neurova-icon.png")).convert("RGBA")
    logo = logo.resize((44, 44), Image.LANCZOS)
    img.paste(logo, (W - 52, (H - 44) // 2), logo)
    img.save(os.path.join(OUT, "..", "header.bmp"))


def make_sidebar() -> None:
    """完成页侧栏 164x314（MUI 欢迎栏同规格）：深靛渐变 + Logo + 品牌字。"""
    W, H = 164, 314
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))
    rnd = random.Random(7)
    for _ in range(50):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        r = rnd.choice([1, 1, 2])
        v = rnd.randint(50, 150)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(v, v, min(255, v + 30)))
    logo = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "NeurUI", "public", "img", "neurova-icon.png")).convert("RGBA")
    logo = logo.resize((84, 84), Image.LANCZOS)
    img.paste(logo, ((W - 84) // 2, 56), logo)
    t1, t2 = "Neurova", "智 星"
    f1 = _font(20, bold=True)
    w1 = d.textlength(t1, font=f1)
    d.text(((W - w1) / 2, 156), t1, font=f1, fill=TEXT_MAIN)
    f2 = _font(16)
    w2 = d.textlength(t2, font=f2)
    d.text(((W - w2) / 2, 186), t2, font=f2, fill=TEXT_SUB)
    img.save(os.path.join(OUT, "..", "sidebar.bmp"))


if __name__ == "__main__":
    make_hero("zh")
    make_hero("en")
    make_button()
    make_header()
    make_sidebar()
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f, os.path.getsize(p) // 1024, "KB")
