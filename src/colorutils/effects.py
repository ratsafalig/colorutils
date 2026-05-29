from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .processor import map_image_to_palette, pixelize_image


EFFECT_LABELS: dict[str, str] = {
    "lospec": "Lospec Recolor",
    "gaussian3": "Gaussian 3x3",
    "laplace": "Laplace",
    "sobel": "Sobel",
    "erosion": "Erosion",
    "dilation": "Dilation",
    "pixelize": "Pixelize",
    "pixel_perfect": "Pixel Perfect",
}


@dataclass
class EffectStep:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    step_id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def label(self) -> str:
        title = EFFECT_LABELS.get(self.kind, self.kind)
        if self.kind == "lospec" and self.params.get("palette_title"):
            return f"{title}: {self.params['palette_title']}"
        return title

    def copy(self) -> "EffectStep":
        return EffectStep(
            kind=self.kind,
            params=dict(self.params),
            enabled=self.enabled,
            step_id=self.step_id,
        )


def make_effect(kind: str) -> EffectStep:
    return EffectStep(kind=kind, params=default_params(kind))


def default_params(kind: str) -> dict[str, Any]:
    if kind == "lospec":
        return {"colors": [], "palette_title": "", "preserve_alpha": True}
    if kind == "gaussian3":
        return {"iterations": 1, "strength": 100}
    if kind == "laplace":
        return {"strength": 100, "mode": "edges"}
    if kind == "sobel":
        return {"strength": 100, "grayscale": True}
    if kind in {"erosion", "dilation"}:
        return {"size": 3, "iterations": 1}
    if kind == "pixelize":
        return {"algorithm": "average", "pixel_size": 8, "levels": 8, "strength": 100}
    if kind == "pixel_perfect":
        return {"pixel_size": 4, "levels": 12, "snap_colors": True}
    return {}


def apply_effect_stack(image: Image.Image, steps: list[EffectStep]) -> Image.Image:
    result = image.convert("RGBA")
    for step in steps:
        if step.enabled:
            result = apply_effect(result, step)
    return result


def apply_effect(image: Image.Image, step: EffectStep) -> Image.Image:
    params = step.params
    kind = step.kind
    if kind == "lospec":
        colors = params.get("colors") or []
        if not colors:
            return image.convert("RGBA")
        return map_image_to_palette(image, colors, preserve_alpha=bool(params.get("preserve_alpha", True)))
    if kind == "gaussian3":
        return _blend(image, _gaussian3(image, int(params.get("iterations", 1))), params.get("strength", 100))
    if kind == "laplace":
        return _laplace(image, strength=float(params.get("strength", 100)), mode=str(params.get("mode", "edges")))
    if kind == "sobel":
        return _sobel(image, strength=float(params.get("strength", 100)), grayscale=bool(params.get("grayscale", True)))
    if kind == "erosion":
        return _morph(image, "erosion", int(params.get("size", 3)), int(params.get("iterations", 1)))
    if kind == "dilation":
        return _morph(image, "dilation", int(params.get("size", 3)), int(params.get("iterations", 1)))
    if kind == "pixelize":
        return pixelize_image(
            image,
            algorithm=str(params.get("algorithm", "average")),
            pixel_size=int(params.get("pixel_size", 8)),
            levels=int(params.get("levels", 8)),
            strength=float(params.get("strength", 100)) / 100.0,
        )
    if kind == "pixel_perfect":
        result = pixelize_image(
            image,
            algorithm="nearest",
            pixel_size=int(params.get("pixel_size", 4)),
            levels=int(params.get("levels", 12)),
        )
        if params.get("snap_colors", True):
            result = pixelize_image(
                result,
                algorithm="posterize",
                pixel_size=max(1, int(params.get("pixel_size", 4))),
                levels=int(params.get("levels", 12)),
            )
        return result
    return image.convert("RGBA")


def _gaussian3(image: Image.Image, iterations: int) -> Image.Image:
    result = image.convert("RGBA")
    kernel = ImageFilter.Kernel((3, 3), (1, 2, 1, 2, 4, 2, 1, 2, 1), scale=16)
    for _ in range(max(1, min(12, iterations))):
        result = result.filter(kernel)
    return result


def _laplace(image: Image.Image, *, strength: float, mode: str) -> Image.Image:
    rgba = image.convert("RGBA")
    rgb = rgba.convert("RGB")
    kernel = ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128)
    edges = rgb.filter(kernel).convert("RGBA")
    edges.putalpha(rgba.getchannel("A"))
    if mode == "add":
        arr = np.asarray(rgba, dtype=np.int16).copy()
        edge_arr = np.asarray(edges, dtype=np.int16)
        amount = max(0.0, min(3.0, strength / 100.0))
        arr[..., :3] = np.clip(arr[..., :3] + (edge_arr[..., :3] - 128) * amount, 0, 255)
        return Image.fromarray(arr.astype(np.uint8), mode="RGBA")
    return _blend(rgba, edges, strength)


def _sobel(image: Image.Image, *, strength: float, grayscale: bool) -> Image.Image:
    rgba = image.convert("RGBA")
    gray = np.asarray(ImageOps.grayscale(rgba), dtype=np.float32)
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    magnitude = np.sqrt(gx * gx + gy * gy)
    magnitude *= max(0.0, min(4.0, strength / 100.0))
    magnitude = np.clip(magnitude, 0, 255).astype(np.uint8)
    if grayscale:
        out = np.dstack([magnitude, magnitude, magnitude, np.asarray(rgba.getchannel("A"), dtype=np.uint8)])
        return Image.fromarray(out, mode="RGBA")
    arr = np.asarray(rgba, dtype=np.uint8).copy()
    arr[..., :3] = np.clip(arr[..., :3].astype(np.int16) + magnitude[..., None].astype(np.int16), 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


def _morph(image: Image.Image, kind: str, size: int, iterations: int) -> Image.Image:
    size = max(3, min(15, int(size)))
    if size % 2 == 0:
        size += 1
    result = image.convert("RGBA")
    filter_obj = ImageFilter.MinFilter(size) if kind == "erosion" else ImageFilter.MaxFilter(size)
    for _ in range(max(1, min(12, iterations))):
        alpha = result.getchannel("A")
        result = result.filter(filter_obj)
        result.putalpha(alpha)
    return result


def _blend(original: Image.Image, changed: Image.Image, strength: Any) -> Image.Image:
    amount = max(0.0, min(1.0, float(strength) / 100.0))
    return Image.blend(original.convert("RGBA"), changed.convert("RGBA"), amount)
