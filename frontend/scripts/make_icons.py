"""Draw vexsim's icons into public/icons: a robot seen from above, its front edge thick, on a
blue tile (the design of icons/vexsim.svg). The app's pages and window use them, and
`vexsim shortcut` gives them to the shortcuts it makes (.ico on Windows, .icns on macOS).

Run it with a Python that has Pillow, then `npm run build`:  python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

BLUE = "#2a78d6"
ICONS = Path(__file__).resolve().parents[1] / "public" / "icons"

# The design, on a 32-unit square
SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect x="3" y="3" width="26" height="26" rx="6" fill="#2a78d6"/>
  <rect x="10" y="11" width="12" height="10" rx="1.5" fill="none" stroke="#fff" stroke-width="2.5"/>
  <path d="M22 11v10" stroke="#fff" stroke-width="4"/>
</svg>
"""


def draw(size: int) -> Image.Image:
    """The icon, ``size`` pixels square: drawn 8 times bigger and scaled down, for smooth
    edges."""
    big = size * 8
    k = big / 32
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle([3 * k, 3 * k, 29 * k, 29 * k], radius=6 * k, fill=BLUE)
    # the robot: a 2.5-unit line around (10, 11)-(22, 21) with corners of 1.5, its front 4 wide
    box = [8.75 * k, 9.75 * k, 23.25 * k, 22.25 * k]
    pen.rounded_rectangle(box, radius=2.75 * k, outline="white", width=round(2.5 * k))
    pen.rectangle([20 * k, 11 * k, 24 * k, 21 * k], fill="white")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    (ICONS / "vexsim.svg").write_text(SVG)
    for size in (192, 512):
        draw(size).save(ICONS / f"vexsim-{size}.png", optimize=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(ICONS / "vexsim.ico", sizes=[(s, s) for s in sizes])
    draw(1024).save(ICONS / "vexsim.icns")
    for path in sorted(ICONS.iterdir()):
        print(f"{path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
