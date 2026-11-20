"""Render the original setup illustration, its motion, and local preview images."""
import math
from pathlib import Path
import time

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:
    Image = ImageOps = ImageTk = None


ASSETS = Path(__file__).resolve().parent / 'assets'
_SPRITE_CENTER = (476, 490)  # Centre of the crop in generate_setup_art.py.


def _blend(start, end, amount):
    values = (round(a + (b - a) * amount) for a, b in zip(start, end))
    return '#%02x%02x%02x' % tuple(values)


def load_preview(path: Path):
    if Image is None:
        return None
    try:
        with Image.open(path) as source:
            if not 0 < source.width <= 4096 or not 0 < source.height <= 4096:
                return None
            return source.convert('RGBA')
    except (OSError, Image.DecompressionBombError):
        return None


class HeroArt:
    """Keep one scaled image per role so text changes do not resize the artwork."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.hero = load_preview(ASSETS / 'setup-hero.png')
        self.bloom = load_preview(ASSETS / 'setup-bloom.png')
        self.mark = load_preview(ASSETS / 'setup.ico')
        self.cache = {}
        self.scene = None
        self.sprite_size = None
        self.sprite_base = None
        self.poses = {}
        self.started_at = time.monotonic()

    def _draw(self, role, source, x, y, width, height, center, anchor):
        if source is None:
            return None
        size = (max(1, round(width)), max(1, round(height)))
        cached_source, cached_size, cached_center, photo = self.cache.get(role, (None, None, None, None))
        if cached_source is not source or cached_size != size or cached_center != center:
            fitted = ImageOps.fit(source, size, Image.Resampling.LANCZOS, centering=center)
            photo = ImageTk.PhotoImage(fitted, master=self.canvas)
            self.cache[role] = (source, size, center, photo)
        return self.canvas.create_image(x, y, image=photo, anchor=anchor, tags='visual')

    def draw(self, x, y, width, height, *, animate=False):
        self._draw('scene', self.hero, x, y, width, height, (.5, .5), 'nw')
        if self.hero is not None and self.bloom is not None:
            self.scene = _BloomScene(self.canvas, x, y, width, height, self._pose, animate)
            self.scene.paint(time.monotonic() - self.started_at if animate else 0.0)

    def clear_motion(self):
        self.scene = None

    @property
    def animating(self):
        return self.scene is not None and self.scene.animate

    def tick(self):
        if self.animating and self.canvas.winfo_viewable():
            self.scene.paint(time.monotonic() - self.started_at)

    def _pose(self, scale, angle):
        size = (max(1, round(self.bloom.width * scale)), max(1, round(self.bloom.height * scale)))
        if self.sprite_size != size:
            self.sprite_size = size
            self.sprite_base = self.bloom.resize(size, Image.Resampling.LANCZOS)
            self.poses.clear()
        if angle not in self.poses:
            image = self.sprite_base
            if angle:
                image = image.rotate(angle, Image.Resampling.BICUBIC)
            self.poses[angle] = ImageTk.PhotoImage(image, master=self.canvas)
        return self.poses[angle]

    def brand_mark(self, x, y, size):
        return self._draw('mark', self.mark, x, y, size, size, (.5, .5), 'center')

    def cover(self, source, x, y, size):
        return self._draw('cover', source, x, y, size, size, (.5, .5), 'nw')


class _BloomScene:
    """Move only canvas items and reuse a few small turns of the bloom sprite."""

    def __init__(self, canvas, x, y, width, height, pose, animate):
        self.canvas = canvas
        self.pose = pose
        self.animate = animate
        self.scale = max(width / 900, height / 1125)
        self.origin = (x + (width - self.scale * 900) / 2, y + (height - self.scale * 1125) / 2)
        self.bounds = (x, y, x + width, y + height)
        self.angle = None

        self.behind = self._trail() if animate else []
        self.sprite = canvas.create_image(0, 0, image=pose(self.scale, 0), tags='visual')
        front = [self._orbit(t / 24) for t in range(10, 65)]
        front = [point for point in front if self._inside(point)]
        if len(front) > 1:
            canvas.create_line(*front, fill='#72b8be', width=max(1, self.scale * 1.35), tags='visual')
        self.ahead = self._trail() if animate else []
        self.stars = []
        if animate:
            for px, py, phase in ((168, 307, .2), (702, 169, 1.8), (761, 670, 3.3), (172, 691, 4.8)):
                point = self._point(px, py)
                if self._inside(point):
                    star = canvas.create_polygon([0] * 8, outline='', tags='visual')
                    self.stars.append((star, point, phase))

    def _point(self, x, y):
        return self.origin[0] + x * self.scale, self.origin[1] + y * self.scale

    def _inside(self, point):
        left, top, right, bottom = self.bounds
        return left + 7 * self.scale <= point[0] <= right - 7 * self.scale and top <= point[1] <= bottom

    def _orbit(self, phase):
        dx, dy = 393 * math.cos(phase), 111 * math.sin(phase)
        c, s = math.cos(-.59), math.sin(-.59)
        return self._point(451 + c * dx - s * dy, 518 + s * dx + c * dy)

    def _trail(self):
        head = self.canvas.create_oval(0, 0, 0, 0, outline='', state='hidden', tags='visual')
        return [head] + [self.canvas.create_line(0, 0, 0, 0, capstyle='round', state='hidden', tags='visual')
                         for _ in range(19)]

    def paint(self, t):
        swing = math.sin(t * 1.07)
        angle = round(3 * swing) * 2
        if angle != self.angle:
            self.canvas.itemconfigure(self.sprite, image=self.pose(self.scale, angle))
            self.angle = angle
        x, y = self._point(_SPRITE_CENTER[0] + 10 * math.sin(t * .69), _SPRITE_CENTER[1] - 14 * swing)
        self.canvas.coords(self.sprite, x, y)

        for i, (behind, ahead) in enumerate(zip(self.behind, self.ahead)):
            phase = (.7 + t * .73 - i * .033) % math.tau
            above = .40 <= phase <= 2.66
            active, hidden = (ahead, behind) if above else (behind, ahead)
            self.canvas.itemconfigure(hidden, state='hidden')
            point = self._orbit(phase)
            next_point = self._orbit(phase + .033)
            if not self._inside(point) or (i and not self._inside(next_point)):
                self.canvas.itemconfigure(active, state='hidden')
                continue
            intensity = 1 - i / len(self.ahead)
            radius = self.scale * (.8 + 6 * intensity ** 2)
            x, y = point
            color = _blend((75, 131, 173), (255, 248, 181) if i < 4 else (150, 251, 235), intensity)
            if i == 0:
                self.canvas.coords(active, x - radius, y - radius, x + radius, y + radius)
                self.canvas.itemconfigure(active, state='normal', fill=color)
            else:
                self.canvas.coords(active, x, y, *next_point)
                self.canvas.itemconfigure(active, state='normal', fill=color, width=max(1, radius))

        for star, (x, y), phase in self.stars:
            pulse = ((1 + math.sin(t * 1.65 + phase)) * .5) ** 3
            radius = (1.7 + 8 * pulse) * self.scale
            self.canvas.coords(star, x - radius * .63, y, x, y - radius, x + radius * .63, y, x, y + radius)
            self.canvas.itemconfigure(star, fill=_blend((159, 225, 248), (255, 245, 192), pulse))
