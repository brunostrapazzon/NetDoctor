"""Gera netdoctor/ui/netdoctor.ico (rodar uma vez; o .ico gerado é commitado).

Desenho simples e reproduzível: um círculo azul com o símbolo de Wi-Fi e um
"✔" verde. Requer Pillow, que não é dependência do projeto:

    .venv\\Scripts\\pip install pillow
    .venv\\Scripts\\python packaging\\make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
BLUE = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)
GREEN = (34, 197, 94, 255)


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, SIZE - 8, SIZE - 8), fill=BLUE)
    cx, cy = SIZE // 2, 178
    for radius in (40, 76, 112):
        box = (cx - radius, cy - radius, cx + radius, cy + radius)
        d.arc(box, start=225, end=315, fill=WHITE, width=18)
    d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=WHITE)
    # selo verde no canto inferior direito
    d.ellipse((150, 150, 246, 246), fill=GREEN, outline=WHITE, width=8)
    d.line([(172, 199), (191, 218), (225, 180)], fill=WHITE, width=14, joint="curve")
    return img


def main() -> None:
    out = Path(__file__).parent.parent / "netdoctor" / "ui" / "netdoctor.ico"
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    draw().save(out, sizes=sizes)
    print(out)


if __name__ == "__main__":
    main()
