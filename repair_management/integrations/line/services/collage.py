
from __future__ import annotations

from io import BytesIO
from statistics import median

from PIL import Image, ImageOps


BACKGROUND = (255, 255, 255)
MAX_SOURCE_EDGE = 1800
DEFAULT_JPEG_QUALITY = 85


def _normalize_image(image_bytes):
    with Image.open(BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

    width, height = image.size
    longest = max(width, height)
    if longest > MAX_SOURCE_EDGE:
        scale = MAX_SOURCE_EDGE / float(longest)
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.LANCZOS,
        )
    return image


def _cell_size(images):
    widths = sorted(image.width for image in images)
    heights = sorted(image.height for image in images)
    median_width = int(median(widths)) if widths else 1200
    median_height = int(median(heights)) if heights else 1200
    max_width = max(widths) if widths else median_width
    max_height = max(heights) if heights else median_height

    cell_width = min(max(median_width, int(max_width * 0.85)), MAX_SOURCE_EDGE)
    cell_height = min(max(median_height, int(max_height * 0.85)), MAX_SOURCE_EDGE)
    return max(cell_width, 400), max(cell_height, 400)


def _fit_inside(image, cell_width, cell_height):
    copy = image.copy()
    copy.thumbnail((cell_width, cell_height), Image.LANCZOS)
    return copy


def _paste_center(canvas, image, x, y, cell_width, cell_height):
    placed = _fit_inside(image, cell_width, cell_height)
    dx = x + max((cell_width - placed.width) // 2, 0)
    dy = y + max((cell_height - placed.height) // 2, 0)
    canvas.paste(placed, (dx, dy))


def _jpeg_quality(value=None):
    try:
        quality = int(value)
    except (TypeError, ValueError):
        quality = DEFAULT_JPEG_QUALITY
    return min(max(quality, 40), 95)


def create_collage(raw_images, quality=None):
    if not raw_images:
        raise ValueError("No images were provided for collage creation")

    images = [_normalize_image(image_bytes) for image_bytes in raw_images]
    if len(images) == 1:
        output = BytesIO()
        images[0].save(output, format="JPEG", quality=_jpeg_quality(quality), optimize=True)
        return output.getvalue()

    rows = []
    index = 0
    while index < len(images):
        rows.append(images[index:index + 2])
        index += 2

    cell_width, cell_height = _cell_size(images)
    gap = max(16, int(min(cell_width, cell_height) * 0.03))
    padding = gap
    max_columns = 2

    canvas_width = (padding * 2) + (cell_width * max_columns) + gap
    canvas_height = (padding * 2) + (cell_height * len(rows)) + (gap * max(len(rows) - 1, 0))

    canvas = Image.new("RGB", (canvas_width, canvas_height), BACKGROUND)

    y = padding
    for row in rows:
        columns = len(row)
        row_width = (cell_width * columns) + (gap * max(columns - 1, 0))
        x = padding + max((canvas_width - (padding * 2) - row_width) // 2, 0)
        for image in row:
            _paste_center(canvas, image, x, y, cell_width, cell_height)
            x += cell_width + gap
        y += cell_height + gap

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=_jpeg_quality(quality), optimize=True)
    return output.getvalue()
