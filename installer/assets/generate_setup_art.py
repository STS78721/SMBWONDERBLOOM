"""Draw the original WonderBloom setup artwork and Windows icon.

Run with Python, Pillow and NumPy. All shapes, colours and grain are generated
locally from the coordinates below. No artwork or other game input is loaded.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


class Artwork:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.size = (width, height)
        self.y, self.x = np.ogrid[:height, :width]
        self.image = Image.new('RGBA', self.size)

    def mask(self, points):
        # Supersample outlines so diagonal contours stay clean in the smaller icons.
        factor = 2
        mask = Image.new('L', (self.width * factor, self.height * factor))
        ImageDraw.Draw(mask).polygon(to_pixels(points, factor), fill=255)
        return mask.resize(self.size, Image.Resampling.LANCZOS)

    def color(self, first, second, factor):
        factor = np.clip(factor, 0, 1)[..., None]
        values = np.array(first, dtype=np.float32) + (np.array(second) - first) * factor
        return np.broadcast_to(values, (self.height, self.width, 3)).copy()

    def layer(self, pixels):
        return Image.fromarray(np.uint8(np.clip(pixels, 0, 255))).convert('RGBA')

    def paint(self, mask, colors):
        layer = self.layer(colors)
        layer.putalpha(mask)
        self.image.alpha_composite(layer)

    def glow(self, x, y, radius, color, strength):
        distance = ((self.x - x) / radius) ** 2 + ((self.y - y) / radius) ** 2
        alpha = Image.fromarray(np.uint8(strength * np.exp(-distance * 2)))
        layer = Image.new('RGBA', self.size, color)
        layer.putalpha(alpha)
        self.image.alpha_composite(layer)


def to_pixels(points, multiplier=1):
    return [(round(x * multiplier), round(y * multiplier)) for x, y in points]


def curve(start, *segments):
    """Sample a cubic path defined by its controls and end points."""
    result = [start]
    for first, second, end in segments:
        x0, y0 = result[-1]
        for index in range(1, 27):
            t = index / 26
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            result.append((a * x0 + b * first[0] + c * second[0] + d * end[0],
                           a * y0 + b * first[1] + c * second[1] + d * end[1]))
    return result


def line_layer(art, points, color, width):
    factor = 2
    overlay = Image.new('RGBA', (art.width * factor, art.height * factor))
    ImageDraw.Draw(overlay).line(to_pixels(points, factor), fill=color,
                                 width=max(1, round(width * factor)), joint='curve')
    art.image.alpha_composite(overlay.resize(art.size, Image.Resampling.LANCZOS))


def sparkle(draw, x, y, radius, color):
    a, b = radius, radius * 0.22
    draw.polygon(to_pixels(((x, y-a), (x+b, y-b), (x+a, y), (x+b, y+b), (x, y+a),
                            (x-b, y+b), (x-a, y), (x-b, y-b))), fill=color)


def bloom(art, x, y, scale):
    petals = (
        (125, (35, 36, 168), (146, 121, 255), (228, 191, 255)),
        (200, (17, 99, 177), (30, 221, 244), (180, 255, 251)),
        (274, (17, 117, 107), (109, 237, 179), (218, 255, 197)),
        (346, (167, 65, 77), (255, 171, 89), (255, 239, 172)),
        (56, (83, 33, 153), (249, 111, 184), (255, 213, 233)),
    )
    outline = curve((0.03, -0.07), ((0.26, -0.39), (0.54, -0.56), (0.82, -0.41)),
                    ((1.08, -0.27), (1.05, 0.09), (0.76, 0.22)),
                    ((0.55, 0.32), (0.36, 0.12), (0.10, 0.14)),
                    ((0.02, 0.15), (-0.02, 0.05), (0.03, -0.07)))
    crease = curve((0.19, -0.02), ((0.36, -0.16), (0.53, -0.25), (0.73, -0.26)),
                   ((0.82, -0.26), (0.89, -0.25), (0.92, -0.21)))
    for angle, shade, base, highlight in petals:
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

        def transform(points, dx=0, dy=0):
            return [(x + dx + (u*c - v*s)*scale, y + dy + (u*s + v*c)*scale) for u, v in points]

        points = transform(outline)
        art.paint(art.mask(transform(outline, 0, scale * 0.037)).filter(ImageFilter.GaussianBlur(scale * 0.021)),
                  art.color((18, 14, 44), (40, 18, 83), (art.y - y) / scale))
        along = ((art.x - x)*c + (art.y - y)*s) / scale
        across = (-(art.x - x)*s + (art.y - y)*c) / scale
        reflected = np.exp(-((across + 0.30) / 0.24) ** 2 - ((along - 0.72) / 0.62) ** 2)
        lit = art.color(shade, base, along * 0.72 + (0.23 - across) * 0.72)
        wash = reflected[..., None] * 0.78
        lit = lit * (1 - wash) + np.array(highlight) * wash
        art.paint(art.mask(points), lit)
        line_layer(art, transform(crease), (*highlight, 83), scale * 0.005)

    # Layer a soft contact shadow and a sunlit centre over the roots of the folded petals.
    radius = scale * 0.175
    art.glow(x + radius * 0.37, y + radius * 0.68, radius * 1.85, (37, 24, 74), 196)
    orb = [(x + radius * math.cos(i * math.tau / 96), y + radius * math.sin(i * math.tau / 96))
           for i in range(96)]
    orb_light = 1 - np.hypot((art.x - x + radius * 0.42) / (radius * 1.68),
                            (art.y - y + radius * 0.52) / (radius * 1.67))
    art.paint(art.mask(orb), art.color((242, 133, 50), (255, 244, 165), orb_light))


def ellipse_path(x, y, width, height, rotation, start=0.0, end=math.tau):
    c, s = math.cos(rotation), math.sin(rotation)
    return [(x + (a*c - b*s), y + (a*s + b*c)) for t in np.linspace(start, end, 220)
            for a, b in [(width*math.cos(t), height*math.sin(t))]]


def landscape(art):
    # Broad, simple silhouettes at the bottom keep the portal shape readable.
    for bottom, top, outline in (
        ((22, 27, 75), (61, 88, 137), ((0, 817), ((163, 713), (243, 684), (357, 761)),
                                    ((502, 856), (578, 793), (653, 739)), ((772, 654), (854, 677), (900, 735)))),
        ((16, 27, 64), (38, 83, 119), ((0, 895), ((157, 778), (266, 825), (355, 859)),
                                    ((516, 922), (592, 807), (674, 852)), ((754, 888), (812, 830), (900, 800)))),
        ((12, 20, 44), (24, 49, 88), ((0, 973), ((150, 908), (278, 861), (401, 921)),
                                   ((578, 1008), (679, 990), (778, 940)), ((823, 919), (883, 900), (900, 914)))),
    ):
        path = curve(outline[0], *outline[1:]) + [(900, 1125), (0, 1125)]
        art.paint(art.mask(path), art.color(top, bottom, (art.y - 701) / 385))


def hero():
    art = Artwork(900, 1125)
    art.image = art.layer(art.color((16, 18, 47), (31, 30, 77), art.y / art.height))
    art.glow(575, 382, 563, (51, 66, 157), 223)
    art.glow(725, 645, 464, (36, 131, 141), 168)
    art.glow(184, 747, 332, (91, 57, 141), 123)
    art.glow(486, 474, 330, (84, 124, 200), 118)

    # Hushed drawing marks around the central form, with the foreground orbit added later.
    for radius, alpha in ((330, 39), (372, 30), (416, 18)):
        points = ellipse_path(499, 495, radius, radius, -0.13, -1.65, 3.52)
        line_layer(art, points, (193, 214, 255, alpha), 1)
    ring_x, ring_y = 451, 518
    for width, height, alpha in ((393, 111, 122), (424, 141, 56)):
        line_layer(art, ellipse_path(ring_x, ring_y, width, height, -0.59), (153, 227, 234, alpha), 1)

    landscape(art)
    art.glow(470, 685, 305, (86, 118, 157), 53)
    stars = Image.new('RGBA', art.size)
    draw = ImageDraw.Draw(stars)
    for x, y, size, color in (
        (168, 307, 12, (159, 225, 248, 224)), (702, 169, 21, (255, 226, 153, 241)),
        (761, 670, 16, (150, 255, 217, 235)), (172, 691, 11, (245, 186, 252, 204)),
        (683, 768, 6, (255, 213, 171, 218)), (252, 231, 5, (255, 228, 167, 218)),
        (843, 428, 10, (141, 206, 255, 227)), (525, 114, 6, (159, 225, 248, 197)),
    ):
        sparkle(draw, x, y, size, color)
    rng = np.random.default_rng(131)
    for x, y, r in zip(rng.uniform(40, 865, 51), rng.uniform(70, 857, 51), rng.uniform(0.7, 2.2, 51)):
        if (x - 479)**2 + (y - 495)**2 > 306**2:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(193, 225, 255, int(rng.integers(43, 135))))
    art.image.alpha_composite(stars)
    # Gentle dither reduces banding but still compresses smoothly for the native installer.
    rgb = np.asarray(art.image.convert('RGB'), dtype=np.int16)
    rgb = np.uint8(np.clip(rgb + rng.integers(-1, 2, (*rgb.shape[:2], 1), dtype=np.int16), 0, 255))
    return Image.fromarray(rgb)


def moving_bloom():
    # The canvas positions this crop in the landscape's 900×1125 coordinates.
    art = Artwork(900, 1125)
    bloom(art, 479, 495, 290)
    return art.image.crop((132, 165, 820, 815))


def icon():
    art = Artwork(384, 384)
    inset = Image.new('L', art.size)
    ImageDraw.Draw(inset).rounded_rectangle((10, 10, 374, 374), 91, fill=255)
    art.paint(inset, art.color((33, 32, 83), (12, 20, 52), (art.x + art.y) / 700))
    # The artwork will be reduced to 16px by Explorer, so simplify the ornament.
    bloom(art, 198, 198, 155)
    return art.image.resize((256, 256), Image.Resampling.LANCZOS)


def main():
    directory = Path(__file__).resolve().parent
    hero().save(directory / 'setup-hero.png', optimize=True)
    moving_bloom().save(directory / 'setup-bloom.png', optimize=True)
    icon().save(directory / 'setup.ico', sizes=((16, 16), (24, 24), (32, 32), (48, 48),
                                               (64, 64), (128, 128), (256, 256)))


if __name__ == '__main__':
    main()
