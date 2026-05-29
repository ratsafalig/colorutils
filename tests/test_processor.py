from PIL import Image

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
