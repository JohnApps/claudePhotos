# co_extract_exif.py
import os
from datetime import datetime
from fractions import Fraction

import psycopg
from PIL import Image, ExifTags

# Disable Pillow decompression bomb protection
Image.MAX_IMAGE_PIXELS = None

SOURCE_DIR = os.environ["SOURCE_DIR"]

# --- helpers ---------------------------------------------------------------

def normalize_exif_value(value):
    """Normalize EXIF values to psycopg‑safe Python types."""
    if value is None:
        return None

    # Pillow IFDRational
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            return float(value.numerator) / float(value.denominator)
        except Exception:
            return str(value)

    # Tuple rational
    if isinstance(value, tuple) and len(value) == 2:
        try:
            return float(value[0]) / float(value[1])
        except Exception:
            return f"{value[0]}/{value[1]}"

    # Empty strings should become None
    if value == "":
        return None

    return value


def clean_str(value):
    """Remove NUL bytes from strings for PostgreSQL text fields."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def extract_exif(path):
    """Return (exif_dict, width, height) with normalized values."""
    try:
        img = Image.open(path)
        width, height = img.size
        raw = img._getexif() or {}
    except Exception:
        return {}, None, None

    exif = {}
    for tag_id, value in raw.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        exif[tag] = normalize_exif_value(value)

    return exif, width, height


def parse_exif(exif):
    """Map EXIF dict to our target columns."""
    def get(tag):
        return exif.get(tag)

    # Aperture
    aperture = get("FNumber")
    if isinstance(aperture, (int, float)):
        aperture = round(aperture, 2)

    # Shutter speed
    shutter = get("ExposureTime")
    if isinstance(shutter, float):
        shutter = f"{Fraction(shutter).limit_denominator()}"

    # Focal length
    focal = get("FocalLength")
    if isinstance(focal, (int, float)):
        focal = f"{focal:.1f} mm"

    # Date taken
    dt = get("DateTimeOriginal")
    if isinstance(dt, str) and dt.strip():
        try:
            dt = datetime.strptime(dt, "%Y:%m:%d %H:%M:%S")
        except Exception:
            dt = None
    else:
        dt = None

    return {
        "aperture": str(aperture) if aperture else None,
        "shutter_speed": shutter,
        "iso": get("ISOSpeedRatings"),
        "focal_length": focal,
        "date_taken": dt,
        "camera_model": get("Model"),
        "lens_model": get("LensModel"),
    }


# --- main ------------------------------------------------------------------

BATCH_SIZE = 500
pending = 0

with psycopg.connect() as conn:
    with conn.cursor() as cur:

        cur.execute("SELECT pathname FROM photos WHERE pathname ILIKE '%.jpg'")
        rows = cur.fetchall()

        for (pathname,) in rows:
            full_path = os.path.join(SOURCE_DIR, pathname)

            if not os.path.exists(full_path):
                print(f"Missing file: {full_path}")
                continue

            file_size = os.path.getsize(full_path)
            exif, width, height = extract_exif(full_path)
            parsed = parse_exif(exif)

            cur.execute(
                """
                UPDATE photos
                SET file_size    = %s,
                    aperture     = %s,
                    shutter_speed= %s,
                    iso          = %s,
                    focal_length = %s,
                    date_taken   = %s,
                    camera_model = %s,
                    lens_model   = %s,
                    width        = %s,
                    height       = %s,
                    analysis_date= NOW(),
                    updated_at   = NOW()
                WHERE pathname   = %s
                """,
                (
                    file_size,
                    clean_str(parsed["aperture"]),
                    clean_str(parsed["shutter_speed"]),
                    parsed["iso"],
                    clean_str(parsed["focal_length"]),
                    parsed["date_taken"],   # always None or valid datetime
                    clean_str(parsed["camera_model"]),
                    clean_str(parsed["lens_model"]),
                    width,
                    height,
                    pathname,
                ),
            )

            pending += 1

            if pending >= BATCH_SIZE:
                conn.commit()
                pending = 0
                print("Committed batch of 500 updates")

        if pending > 0:
            conn.commit()
            print(f"Committed final batch of {pending} updates")

print("EXIF extraction complete.")
