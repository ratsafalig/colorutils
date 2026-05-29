from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

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
    "box_blur": "Box Blur",
    "unsharp": "Unsharp Mask",
    "sharpen": "Sharpen",
    "emboss": "Emboss",
    "median": "Median Filter",
    "edge_enhance": "Edge Enhance",
    "threshold": "Threshold",
    "posterize": "Posterize",
    "invert": "Invert",
    "color_adjust": "Color Adjust",
    "gamma": "Gamma",
    "dog": "Difference of Gaussians",
    "opening": "Opening",
    "closing": "Closing",
    "morph_gradient": "Morph Gradient",
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
    if kind == "box_blur":
        return {"radius": 2, "strength": 100}
    if kind == "unsharp":
        return {"radius": 2, "percent": 150, "threshold": 3}
    if kind in {"sharpen", "emboss", "edge_enhance", "invert"}:
        return {"strength": 100}
    if kind == "median":
        return {"size": 3}
    if kind == "threshold":
        return {"threshold": 128, "invert": False}
    if kind == "posterize":
        return {"bits": 4}
    if kind == "color_adjust":
        return {"brightness": 100, "contrast": 100, "saturation": 100}
    if kind == "gamma":
        return {"gamma": 100}
    if kind == "dog":
        return {"small_radius": 1, "large_radius": 3, "strength": 100}
    if kind in {"opening", "closing", "morph_gradient"}:
        return {"size": 3, "iterations": 1}
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
    if kind == "box_blur":
        changed = image.convert("RGBA").filter(ImageFilter.BoxBlur(max(0, int(params.get("radius", 2)))))
        return _blend(image, changed, params.get("strength", 100))
    if kind == "unsharp":
        return image.convert("RGBA").filter(
            ImageFilter.UnsharpMask(
                radius=max(0, int(params.get("radius", 2))),
                percent=max(0, int(params.get("percent", 150))),
                threshold=max(0, int(params.get("threshold", 3))),
            )
        )
    if kind == "sharpen":
        factor = max(0.0, float(params.get("strength", 100)) / 100.0)
        return ImageEnhance.Sharpness(image.convert("RGBA")).enhance(factor)
    if kind == "emboss":
        changed = image.convert("RGBA").filter(ImageFilter.EMBOSS)
        return _blend(image, changed, params.get("strength", 100))
    if kind == "median":
        return _median_filter(image, int(params.get("size", 3)))
    if kind == "edge_enhance":
        changed = image.convert("RGBA").filter(ImageFilter.EDGE_ENHANCE_MORE)
        return _blend(image, changed, params.get("strength", 100))
    if kind == "threshold":
        return _threshold(image, int(params.get("threshold", 128)), bool(params.get("invert", False)))
    if kind == "posterize":
        return _posterize_rgba(image, int(params.get("bits", 4)))
    if kind == "invert":
        changed = _invert_rgba(image)
        return _blend(image, changed, params.get("strength", 100))
    if kind == "color_adjust":
        return _color_adjust(
            image,
            brightness=float(params.get("brightness", 100)),
            contrast=float(params.get("contrast", 100)),
            saturation=float(params.get("saturation", 100)),
        )
    if kind == "gamma":
        return _gamma(image, float(params.get("gamma", 100)) / 100.0)
    if kind == "dog":
        return _difference_of_gaussians(
            image,
            small_radius=float(params.get("small_radius", 1)),
            large_radius=float(params.get("large_radius", 3)),
            strength=float(params.get("strength", 100)),
        )
    if kind == "opening":
        return _opening_closing(image, "opening", int(params.get("size", 3)), int(params.get("iterations", 1)))
    if kind == "closing":
        return _opening_closing(image, "closing", int(params.get("size", 3)), int(params.get("iterations", 1)))
    if kind == "morph_gradient":
        return _morph_gradient(image, int(params.get("size", 3)))
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
    size = _odd_size(size)
    result = image.convert("RGBA")
    filter_obj = ImageFilter.MinFilter(size) if kind == "erosion" else ImageFilter.MaxFilter(size)
    for _ in range(max(1, min(12, iterations))):
        alpha = result.getchannel("A")
        result = result.filter(filter_obj)
        result.putalpha(alpha)
    return result


def _median_filter(image: Image.Image, size: int) -> Image.Image:
    size = _odd_size(size)
    alpha = image.convert("RGBA").getchannel("A")
    result = image.convert("RGBA").filter(ImageFilter.MedianFilter(size))
    result.putalpha(alpha)
    return result


def _threshold(image: Image.Image, threshold: int, invert: bool) -> Image.Image:
    rgba = image.convert("RGBA")
    gray = np.asarray(ImageOps.grayscale(rgba), dtype=np.uint8)
    mask = gray > max(0, min(255, int(threshold)))
    if invert:
        mask = ~mask
    value = np.where(mask, 255, 0).astype(np.uint8)
    arr = np.dstack([value, value, value, np.asarray(rgba.getchannel("A"), dtype=np.uint8)])
    return Image.fromarray(arr, mode="RGBA")


def _posterize_rgba(image: Image.Image, bits: int) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = ImageOps.posterize(rgba.convert("RGB"), max(1, min(8, int(bits))))
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def _invert_rgba(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = ImageOps.invert(rgba.convert("RGB"))
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def _color_adjust(image: Image.Image, *, brightness: float, contrast: float, saturation: float) -> Image.Image:
    result = image.convert("RGBA")
    result = ImageEnhance.Brightness(result).enhance(max(0.0, brightness / 100.0))
    result = ImageEnhance.Contrast(result).enhance(max(0.0, contrast / 100.0))
    result = ImageEnhance.Color(result).enhance(max(0.0, saturation / 100.0))
    return result


def _gamma(image: Image.Image, gamma: float) -> Image.Image:
    gamma = max(0.05, min(5.0, gamma))
    rgba = image.convert("RGBA")
    arr = np.asarray(rgba, dtype=np.float32).copy()
    arr[..., :3] = 255.0 * np.power(arr[..., :3] / 255.0, 1.0 / gamma)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGBA")


def _difference_of_gaussians(
    image: Image.Image,
    *,
    small_radius: float,
    large_radius: float,
    strength: float,
) -> Image.Image:
    rgba = image.convert("RGBA")
    gray = ImageOps.grayscale(rgba)
    small = np.asarray(gray.filter(ImageFilter.GaussianBlur(max(0.0, small_radius))), dtype=np.int16)
    large = np.asarray(gray.filter(ImageFilter.GaussianBlur(max(0.1, large_radius))), dtype=np.int16)
    diff = np.clip((small - large) * max(0.0, strength / 100.0) + 128, 0, 255).astype(np.uint8)
    out = np.dstack([diff, diff, diff, np.asarray(rgba.getchannel("A"), dtype=np.uint8)])
    return Image.fromarray(out, mode="RGBA")


def _opening_closing(image: Image.Image, mode: str, size: int, iterations: int) -> Image.Image:
    first = "erosion" if mode == "opening" else "dilation"
    second = "dilation" if mode == "opening" else "erosion"
    result = image.convert("RGBA")
    for _ in range(max(1, min(12, iterations))):
        result = _morph(result, first, size, 1)
        result = _morph(result, second, size, 1)
    return result


def _morph_gradient(image: Image.Image, size: int) -> Image.Image:
    dilated = np.asarray(_morph(image, "dilation", size, 1), dtype=np.int16)
    eroded = np.asarray(_morph(image, "erosion", size, 1), dtype=np.int16)
    diff = np.clip(dilated[..., :3] - eroded[..., :3], 0, 255).astype(np.uint8)
    alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
    return Image.fromarray(np.dstack([diff, alpha]), mode="RGBA")


def _odd_size(size: int) -> int:
    size = max(3, min(15, int(size)))
    return size + 1 if size % 2 == 0 else size


def _blend(original: Image.Image, changed: Image.Image, strength: Any) -> Image.Image:
    amount = max(0.0, min(1.0, float(strength) / 100.0))
    return Image.blend(original.convert("RGBA"), changed.convert("RGBA"), amount)
