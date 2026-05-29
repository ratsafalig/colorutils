from PIL import Image

from colorutils.app import display_image_size
from colorutils.effects import apply_effect_stack, make_effect
from colorutils.processor import (
    crop_box,
    find_image_block,
    hex_to_rgb,
    histogram_rgb,
    image_statistics,
    map_image_to_palette,
    pixelize_image,
)


def test_hex_to_rgb() -> None:
    assert hex_to_rgb("#0f8") == (0, 255, 136)
    assert hex_to_rgb("112233") == (17, 34, 51)


def test_display_image_size_scales_up_and_down() -> None:
    assert display_image_size((200, 100), (800, 600)) == (800, 400)
    assert display_image_size((1600, 900), (800, 600)) == (800, 450)
    assert display_image_size((100, 400), (800, 600)) == (150, 600)


def test_map_image_to_nearest_palette_color() -> None:
    image = Image.new("RGB", (2, 1))
    image.putpixel((0, 0), (250, 10, 10))
    image.putpixel((1, 0), (10, 10, 240))

    mapped = map_image_to_palette(image, ["ff0000", "0000ff"])

    assert mapped.getpixel((0, 0)) == (255, 0, 0, 255)
    assert mapped.getpixel((1, 0)) == (0, 0, 255, 255)


def test_statistics_histogram_and_pixel_effects() -> None:
    image = Image.new("RGBA", (16, 16), (120, 80, 40, 255))
    stats = image_statistics(image)
    hist = histogram_rgb(image)
    pixelized = pixelize_image(image, algorithm="posterize", pixel_size=4, levels=4)

    assert stats["size"] == (16, 16)
    assert len(stats["dominant_colors"]) >= 1
    assert sum(hist["r"]) == 256
    assert pixelized.size == image.size


def test_find_image_block_returns_valid_crop() -> None:
    image = Image.new("RGB", (100, 80), "white")
    for x in range(55, 85, 5):
        for y in range(20, 65):
            image.putpixel((x, y), (10, 10, 10))
    for y in range(20, 65, 5):
        for x in range(55, 85):
            image.putpixel((x, y), (10, 10, 10))

    box = find_image_block(image, algorithm="structure", block_percent=35, sensitivity=60)
    crop = crop_box(image, box)

    assert 0 <= box[0] < box[2] <= image.width
    assert 0 <= box[1] < box[3] <= image.height
    assert crop.width > 0 and crop.height > 0


def test_effect_stack_applies_steps_in_order() -> None:
    image = Image.new("RGBA", (8, 8), (250, 10, 10, 255))
    recolor = make_effect("lospec")
    recolor.params["colors"] = ["000000", "ff0000"]
    blur = make_effect("gaussian3")
    blur.params["strength"] = 50

    result = apply_effect_stack(image, [recolor, blur])

    assert result.size == image.size
    assert result.getpixel((0, 0))[3] == 255


def test_effect_stack_supports_edges_morphology_and_pixel_perfect() -> None:
    image = Image.new("RGBA", (16, 16), (255, 255, 255, 255))
    for x in range(4, 12):
        for y in range(4, 12):
            image.putpixel((x, y), (0, 0, 0, 255))
    steps = [make_effect("sobel"), make_effect("dilation"), make_effect("pixel_perfect")]

    result = apply_effect_stack(image, steps)

    assert result.size == image.size
    assert result.mode == "RGBA"


def test_effect_stack_supports_extended_operators() -> None:
    image = Image.new("RGBA", (20, 20), (120, 80, 40, 255))
    steps = [
        make_effect("color_adjust"),
        make_effect("pc98_dither"),
        make_effect("gamma"),
        make_effect("threshold"),
        make_effect("posterize"),
        make_effect("invert"),
        make_effect("contrast"),
        make_effect("auto_contrast"),
        make_effect("clarity"),
        make_effect("vibrance"),
        make_effect("denoise"),
        make_effect("depth_layers"),
        make_effect("box_blur"),
        make_effect("unsharp"),
        make_effect("emboss"),
        make_effect("median"),
        make_effect("dog"),
        make_effect("opening"),
        make_effect("closing"),
        make_effect("morph_gradient"),
    ]

    result = apply_effect_stack(image, steps)

    assert result.size == image.size
    assert result.mode == "RGBA"


def test_contrast_effect_increases_channel_spread() -> None:
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    image.putpixel((0, 0), (80, 80, 80, 255))
    image.putpixel((1, 0), (176, 176, 176, 255))
    step = make_effect("contrast")
    step.params["amount"] = 200

    result = apply_effect_stack(image, [step])

    assert result.getpixel((0, 0))[0] < 80
    assert result.getpixel((1, 0))[0] > 176
    assert result.getpixel((0, 0))[3] == 255


def test_enhancement_effects_preserve_size_mode_and_alpha() -> None:
    image = Image.new("RGBA", (5, 5), (96, 112, 128, 255))
    image.putpixel((2, 2), (255, 255, 255, 255))
    steps = [
        make_effect("auto_contrast"),
        make_effect("clarity"),
        make_effect("vibrance"),
        make_effect("denoise"),
    ]

    result = apply_effect_stack(image, steps)

    assert result.size == image.size
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 255


def test_auto_contrast_expands_luma_range() -> None:
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    image.putpixel((0, 0), (64, 64, 64, 255))
    image.putpixel((1, 0), (192, 192, 192, 255))
    step = make_effect("auto_contrast")
    step.params["cutoff"] = 0
    step.params["strength"] = 100

    result = apply_effect_stack(image, [step])

    assert result.getpixel((0, 0))[0] == 0
    assert result.getpixel((1, 0))[0] == 255


def test_pc98_dither_maps_to_classic_palette_and_preserves_alpha() -> None:
    image = Image.new("RGBA", (8, 8), (32, 96, 160, 128))
    for y in range(8):
        for x in range(8):
            image.putpixel((x, y), (x * 32, y * 32, 180, 128))
    step = make_effect("pc98_dither")
    step.params["pixel_size"] = 2
    step.params["dither_strength"] = 100
    step.params["scanline_strength"] = 20

    result = apply_effect_stack(image, [step])
    palette = {
        (0, 0, 0),
        (0, 0, 170),
        (170, 0, 0),
        (170, 0, 170),
        (0, 170, 0),
        (0, 170, 170),
        (170, 170, 0),
        (170, 170, 170),
        (85, 85, 85),
        (85, 85, 255),
        (255, 85, 85),
        (255, 85, 255),
        (85, 255, 85),
        (85, 255, 255),
        (255, 255, 85),
        (255, 255, 255),
    }

    assert result.size == image.size
    assert result.mode == "RGBA"
    assert all(result.getpixel((x, y))[:3] in palette for y in range(8) for x in range(8))
    assert result.getpixel((0, 0))[3] == 128


def test_depth_layers_distinguishes_foreground_and_background() -> None:
    image = Image.new("RGBA", (24, 16), (180, 190, 205, 255))
    for y in range(4, 12):
        for x in range(8, 16):
            image.putpixel((x, y), (40, 45, 55, 255))
    step = make_effect("depth_layers")
    step.params["layers"] = "3"
    step.params["foreground_cut"] = 70
    step.params["background_cut"] = 30
    step.params["background_blur"] = 3
    step.params["background_dim"] = 35
    step.params["foreground_boost"] = 60

    result = apply_effect_stack(image, [step])

    assert result.size == image.size
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 255
    assert result.getpixel((0, 0))[:3] != image.getpixel((0, 0))[:3]
