"""Decode reference files locally and save a consistent, metadata-free JPEG."""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BATCH_BYTES = 50 * 1024 * 1024
MAX_FILES = 20


def normalize_reference(data):
    if not data:
        raise ValueError("画像が空です。別の画像を選んでください")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("画像は1枚10MB以下にしてください")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format not in ("JPEG", "PNG", "WEBP") or getattr(original, "n_frames", 1) != 1:
                    raise ValueError("JPEG・PNG・WebPの静止画を選んでください")
                if min(original.size) < 64 or original.width * original.height > 24_000_000:
                    raise ValueError("画像は縦横64ピクセル以上、2400万画素以下にしてください")
                image = ImageOps.exif_transpose(original)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    image = image.convert("RGB")
                image.thumbnail((960, 720))
                output = io.BytesIO()
                image.save(output, "JPEG", quality=90)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("画像を読み込めません。JPEG・PNG・WebPの画像を選んでください") from exc
