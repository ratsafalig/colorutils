from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"Invalid hex color: {value!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def palette_to_rgb(colors: tuple[str, ...] | list[str]) -> list[tuple[int, int, int]]:
    return [hex_to_rgb(color) for color in colors]


def map_image_to_palette(
    image: Image.Image,
    colors: tuple[str, ...] | list[str],
    *,
    preserve_alpha: bool = True,
    chunk_size: int = 65_536,
) -> Image.Image:
    palette = np.asarray(palette_to_rgb(colors), dtype=np.int32)
    if palette.size == 0:
        raise ValueError("Palette is empty")

    source = image.convert("RGBA")
    arr = np.asarray(source, dtype=np.uint8).copy()
    flat_rgb = arr[..., :3].reshape(-1, 3).astype(np.int32)
    output = np.empty_like(flat_rgb, dtype=np.uint8)

    for start in range(0, flat_rgb.shape[0], chunk_size):
        chunk = flat_rgb[start : start + chunk_size]
        diff = chunk[:, None, :] - palette[None, :, :]
        distances = np.sum(diff * diff, axis=2)
        nearest = np.argmin(distances, axis=1)
        output[start : start + chunk_size] = palette[nearest].astype(np.uint8)

    arr[..., :3] = output.reshape(arr.shape[0], arr.shape[1], 3)
    if not preserve_alpha:
        arr[..., 3] = 255
    return Image.fromarray(arr, mode="RGBA")


def fit_image(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail(max_size, Image.Resampling.LANCZOS)
    return fitted


def image_statistics(image: Image.Image, *, sample_size: int = 512) -> dict[str, Any]:
    sample = fit_image(image.convert("RGBA"), (sample_size, sample_size))
    arr = np.asarray(sample, dtype=np.uint8)
    rgb = arr[..., :3].reshape(-1, 3)
    alpha = arr[..., 3].reshape(-1)
    visible = rgb[alpha > 0] if np.any(alpha > 0) else rgb
    mean = np.mean(visible, axis=0)
    median = np.median(visible, axis=0)
    std = np.std(visible, axis=0)
    luminance = visible @ np.array([0.2126, 0.7152, 0.0722])
    return {
        "size": image.size,
        "mode": image.mode,
        "sample_pixels": int(visible.shape[0]),
        "mean_rgb": tuple(int(round(value)) for value in mean),
        "median_rgb": tuple(int(round(value)) for value in median),
        "std_rgb": tuple(int(round(value)) for value in std),
        "min_luma": float(np.min(luminance)),
        "max_luma": float(np.max(luminance)),
        "transparent_pixels_sample": int(np.sum(alpha == 0)),
        "dominant_colors": dominant_colors(sample, count=8),
    }


def dominant_colors(image: Image.Image, *, count: int = 8) -> list[tuple[str, int]]:
    sample = fit_image(image.convert("RGB"), (220, 220))
    quantized = sample.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    colors = quantized.getcolors(maxcolors=sample.width * sample.height) or []
    result: list[tuple[str, int]] = []
    for color_count, index in sorted(colors, reverse=True):
        base = index * 3
        if base + 2 >= len(palette):
            continue
        r, g, b = palette[base : base + 3]
        result.append((f"{r:02x}{g:02x}{b:02x}", int(color_count)))
    return result[:count]


def histogram_rgb(image: Image.Image) -> dict[str, list[int]]:
    hist = image.convert("RGB").histogram()
    return {
        "r": hist[0:256],
        "g": hist[256:512],
        "b": hist[512:768],
    }


def pixelize_image(
    image: Image.Image,
    *,
    algorithm: str = "average",
    pixel_size: int = 8,
    levels: int = 8,
    strength: float = 1.0,
    palette_colors: tuple[str, ...] | list[str] | None = None,
) -> Image.Image:
    pixel_size = max(1, int(pixel_size))
    levels = max(2, min(32, int(levels)))
    strength = max(0.0, min(1.0, float(strength)))
    source = image.convert("RGBA")
    width, height = source.size
    small_size = (max(1, width // pixel_size), max(1, height // pixel_size))
    name = algorithm.lower().replace(" ", "_")

    if name == "nearest":
        small = source.resize(small_size, Image.Resampling.NEAREST)
        result = small.resize(source.size, Image.Resampling.NEAREST)
    elif name == "median":
        result = _median_block_pixelize(source, pixel_size)
    elif name == "posterize":
        result = _posterize_pixelize(source, small_size, levels)
    elif name == "ordered_dither":
        result = _ordered_dither(source, levels=levels, strength=strength)
        result = result.resize(small_size, Image.Resampling.BOX).resize(source.size, Image.Resampling.NEAREST)
    elif name == "palette_nearest" and palette_colors:
        small = source.resize(small_size, Image.Resampling.BOX).resize(source.size, Image.Resampling.NEAREST)
        result = map_image_to_palette(small, palette_colors)
    else:
        small = source.resize(small_size, Image.Resampling.BOX)
        result = small.resize(source.size, Image.Resampling.NEAREST)
    return result


def find_image_block(
    image: Image.Image,
    *,
    algorithm: str = "structure",
    block_percent: int = 35,
    sensitivity: int = 55,
    stride_percent: int = 25,
) -> tuple[int, int, int, int, float]:
    source = fit_image(image.convert("RGB"), (900, 900))
    arr = np.asarray(source, dtype=np.float32)
    gray = np.asarray(ImageOps.grayscale(source), dtype=np.float32)
    edge = _edge_map(gray)
    saturation = _saturation_map(arr)
    contrast = np.abs(gray - float(np.mean(gray))) / 255.0
    name = algorithm.lower().replace(" ", "_")
    if name == "color_saliency":
        score_map = saturation * 0.65 + contrast * 0.35
    elif name == "bright_contrast":
        score_map = contrast
    else:
        vertical = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1])) / 255.0
        horizontal = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :])) / 255.0
        score_map = edge * 0.55 + vertical * 0.25 + horizontal * 0.20

    height, width = gray.shape
    block = max(32, int(min(width, height) * max(10, min(90, block_percent)) / 100))
    stride = max(8, int(block * max(10, min(90, stride_percent)) / 100))
    threshold = max(0.0, min(1.0, sensitivity / 100.0))
    best_box = (0, 0, min(block, width), min(block, height))
    best_score = -1.0

    for y in range(0, max(1, height - block + 1), stride):
        for x in range(0, max(1, width - block + 1), stride):
            window = score_map[y : y + block, x : x + block]
            density = float(np.mean(window))
            peak = float(np.percentile(window, 85))
            center_bonus = _center_bonus(x, y, block, width, height)
            score = density * (0.55 + threshold * 0.45) + peak * 0.30 + center_bonus * 0.15
            if score > best_score:
                best_score = score
                best_box = (x, y, min(x + block, width), min(y + block, height))

    scale_x = image.width / width
    scale_y = image.height / height
    x1, y1, x2, y2 = best_box
    return (
        int(round(x1 * scale_x)),
        int(round(y1 * scale_y)),
        int(round(x2 * scale_x)),
        int(round(y2 * scale_y)),
        best_score,
    )


def crop_box(image: Image.Image, box: tuple[int, int, int, int, float] | tuple[int, int, int, int]) -> Image.Image:
    x1, y1, x2, y2 = [int(value) for value in box[:4]]
    x1 = max(0, min(image.width - 1, x1))
    y1 = max(0, min(image.height - 1, y1))
    x2 = max(x1 + 1, min(image.width, x2))
    y2 = max(y1 + 1, min(image.height, y2))
    return image.crop((x1, y1, x2, y2))


def save_palette_png(colors: tuple[str, ...] | list[str], path: str | Path, *, swatch_size: int = 48) -> None:
    rgb = palette_to_rgb(colors)
    width = max(1, len(rgb)) * swatch_size
    image = Image.new("RGB", (width, swatch_size), "white")
    for index, color in enumerate(rgb):
        image.paste(color, (index * swatch_size, 0, (index + 1) * swatch_size, swatch_size))
    image.save(path)


def save_palette_gpl(
    colors: tuple[str, ...] | list[str],
    path: str | Path,
    *,
    name: str = "Lospec Palette",
) -> None:
    rows = ["GIMP Palette", f"Name: {name}", "Columns: 8", "#"]
    for color in colors:
        r, g, b = hex_to_rgb(color)
        rows.append(f"{r:3d} {g:3d} {b:3d}\t#{color.strip().lstrip('#').lower()}")
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")


def _median_block_pixelize(image: Image.Image, pixel_size: int) -> Image.Image:
    arr = np.asarray(image, dtype=np.uint8).copy()
    for y in range(0, arr.shape[0], pixel_size):
        for x in range(0, arr.shape[1], pixel_size):
            block = arr[y : y + pixel_size, x : x + pixel_size]
            block[:] = np.median(block.reshape(-1, 4), axis=0).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _posterize_pixelize(image: Image.Image, small_size: tuple[int, int], levels: int) -> Image.Image:
    small = image.resize(small_size, Image.Resampling.BOX)
    arr = np.asarray(small, dtype=np.uint8).copy()
    step = max(1, 255 // (levels - 1))
    arr[..., :3] = np.round(arr[..., :3] / step) * step
    arr[..., :3] = np.clip(arr[..., :3], 0, 255)
    return Image.fromarray(arr, mode="RGBA").resize(image.size, Image.Resampling.NEAREST)


def _ordered_dither(image: Image.Image, *, levels: int, strength: float) -> Image.Image:
    bayer = np.array(
        [
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5],
        ],
        dtype=np.float32,
    )
    arr = np.asarray(image, dtype=np.float32).copy()
    height, width = arr.shape[:2]
    threshold = np.tile((bayer + 0.5) / 16.0 - 0.5, (height // 4 + 1, width // 4 + 1))[:height, :width]
    step = 255.0 / (levels - 1)
    arr[..., :3] = np.round((arr[..., :3] + threshold[..., None] * step * strength) / step) * step
    arr[..., :3] = np.clip(arr[..., :3], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


def _edge_map(gray: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    edge = np.sqrt(gx * gx + gy * gy)
    max_value = float(np.max(edge)) or 1.0
    return edge / max_value


def _saturation_map(arr: np.ndarray) -> np.ndarray:
    rgb = arr[..., :3] / 255.0
    max_c = np.max(rgb, axis=2)
    min_c = np.min(rgb, axis=2)
    return np.where(max_c == 0, 0.0, (max_c - min_c) / max_c)


def _center_bonus(x: int, y: int, block: int, width: int, height: int) -> float:
    cx = x + block / 2
    cy = y + block / 2
    nx = abs(cx - width / 2) / max(1, width / 2)
    ny = abs(cy - height / 2) / max(1, height / 2)
    return max(0.0, 1.0 - (nx + ny) / 2)
