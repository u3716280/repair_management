from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
import json
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps


FONT_FAMILY = "Garuda"
MAX_TEXT_LINES = 2


def _run(args, timeout=60):
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@lru_cache(maxsize=1)
def resolve_garuda_font():
    result = _run(
        ["fc-match", "-f", "%{family}|%{style}|%{file}\n", FONT_FAMILY],
        timeout=15,
    )
    line = (result.stdout or "").strip().splitlines()[0].strip()
    parts = line.split("|", 2)
    if len(parts) != 3:
        raise RuntimeError("Garuda font metadata could not be resolved by fc-match")
    family, style, path = (part.strip() for part in parts)
    if "Garuda" not in family or "Regular" not in style:
        raise RuntimeError(f"Fontconfig resolved an unexpected font: {family} / {style}")
    if not path or not Path(path).is_file():
        raise RuntimeError("Garuda Regular font file could not be resolved by fc-match")
    return path


def environment_check():
    ffmpeg = _run(["ffmpeg", "-version"], timeout=15).stdout.splitlines()[0]
    ffprobe = _run(["ffprobe", "-version"], timeout=15).stdout.splitlines()[0]
    filters = _run(["ffmpeg", "-hide_banner", "-filters"], timeout=20).stdout
    if "drawtext" not in filters:
        raise RuntimeError("FFmpeg drawtext filter is not available")
    font = resolve_garuda_font()

    # Verify Pillow can actually load the resolved Thai font.
    ImageFont.truetype(font, 36)

    return {
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "drawtext": True,
        "font_family": FONT_FAMILY,
        "font_file": font,
        "font_style": "Regular",
    }


def _text_width(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return max(box[2] - box[0], 0)


def _split_two_lines(draw, text, font, max_width):
    text = " ".join(str(text or "").split())
    if not text:
        return [""]
    if _text_width(draw, text, font) <= max_width:
        return [text]

    # Prefer a natural word boundary nearest the middle.
    words = text.split(" ")
    if len(words) > 1:
        choices = []
        for i in range(1, len(words)):
            a = " ".join(words[:i])
            b = " ".join(words[i:])
            wa = _text_width(draw, a, font)
            wb = _text_width(draw, b, font)
            if wa <= max_width and wb <= max_width:
                choices.append((abs(wa - wb), a, b))
        if choices:
            _, a, b = min(choices, key=lambda x: x[0])
            return [a, b]

    # Thai item names may have few spaces. Try character boundaries.
    best = None
    for i in range(1, len(text)):
        a = text[:i].strip()
        b = text[i:].strip()
        if not a or not b:
            continue
        wa = _text_width(draw, a, font)
        wb = _text_width(draw, b, font)
        if wa <= max_width and wb <= max_width:
            score = abs(wa - wb)
            if best is None or score < best[0]:
                best = (score, a, b)
    if best:
        return [best[1], best[2]]
    return None


def _fit_text(image, text, font_path):
    width, _ = image.size
    max_width = int(width * 0.96)
    target = min(84, max(28, int(width * 0.035)))
    minimum = max(20, int(width * 0.014))
    draw = ImageDraw.Draw(image)

    size = target
    while size >= minimum:
        font = ImageFont.truetype(font_path, size)
        lines = _split_two_lines(draw, text, font, max_width)
        if lines and len(lines) <= MAX_TEXT_LINES:
            return font, lines
        size -= 2

    # Last-resort fallback: keep two lines and the minimum font size.
    font = ImageFont.truetype(font_path, minimum)
    lines = _split_two_lines(draw, text, font, max_width)
    return font, lines or [str(text or "")]


def burn_in_image_bytes(image_bytes, text, quality=85):
    if not text:
        raise ValueError("Burn-in text is required for image Burn-in")

    font_path = resolve_garuda_font()
    with Image.open(BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

    font, lines = _fit_text(image, text, font_path)
    width, height = image.size

    padding_x = max(20, int(width * 0.02))
    padding_y = max(12, int(height * 0.014))
    line_spacing = max(6, int(font.size * 0.18))

    probe = ImageDraw.Draw(image)
    line_boxes = [probe.textbbox((0, 0), line, font=font) for line in lines]
    heights = [max(box[3] - box[1], font.size) for box in line_boxes]
    text_height = sum(heights) + line_spacing * max(len(lines) - 1, 0)
    bar_height = text_height + padding_y * 2
    top = max(0, height - bar_height)

    rgba = image.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, top, width, height), fill=(0, 0, 0, 155))

    y = top + padding_y
    for line, line_height in zip(lines, heights):
        draw.text(
            (padding_x, y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
        )
        y += line_height + line_spacing

    final = Image.alpha_composite(rgba, overlay).convert("RGB")
    output = BytesIO()
    final.save(output, format="JPEG", quality=int(quality), optimize=True)
    return output.getvalue()


def probe_video(path):
    result = _run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_type:format=duration,size",
            "-of", "json",
            str(path),
        ],
        timeout=60,
    )
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("Video stream not found")
    width = int(streams[0].get("width") or 0)
    height = int(streams[0].get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid video dimensions")
    return data


def _fit_video_font_size(item_name, font_path, width, height):
    # Use Pillow only for measuring the same Garuda font used by FFmpeg.
    canvas = Image.new("RGB", (max(width, 1), max(height, 1)))
    draw = ImageDraw.Draw(canvas)
    max_width = int(width * 0.94)
    target = min(72, max(24, int(height / 28)))
    minimum = max(18, int(height / 55))

    for size in range(target, minimum - 1, -2):
        font = ImageFont.truetype(font_path, size)
        if _text_width(draw, item_name, font) <= max_width:
            return size
    return minimum


def burn_in_video(input_path, output_path, item_name, timeout=1500):
    if not item_name:
        raise ValueError("Item Name is required for video Burn-in")

    font_path = resolve_garuda_font()
    info = probe_video(input_path)
    stream = (info.get("streams") or [{}])[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    font_size = _fit_video_font_size(item_name, font_path, width, height)

    text_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            prefix="line-burnin-",
            delete=False,
        ) as handle:
            handle.write(str(item_name))
            text_path = handle.name

        # Paths are resolved locally by the server and do not contain user input.
        video_filter = (
            f"drawtext=fontfile={font_path}:"
            f"textfile={text_path}:"
            f"fontcolor=white:"
            f"fontsize={font_size}:"
            f"box=1:"
            f"boxcolor=black@0.60:"
            f"boxborderw=14:"
            f"x=30:"
            f"y=h-text_h-30"
        )

        _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i", str(input_path),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-vf", video_filter,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ],
            timeout=timeout,
        )
        if not Path(output_path).is_file() or Path(output_path).stat().st_size <= 0:
            raise RuntimeError("FFmpeg did not create a valid output file")
        probe_video(output_path)
    finally:
        if text_path:
            try:
                Path(text_path).unlink(missing_ok=True)
            except Exception:
                pass
