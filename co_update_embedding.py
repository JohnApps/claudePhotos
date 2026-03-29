# co_update_embedding.py
"""
Requires:
  pip install psycopg[binary] pillow torch open_clip_torch pgvector
"""

import os
from datetime import datetime
from fractions import Fraction

import psycopg
from pgvector.psycopg import register_vector
from PIL import Image, ExifTags
import torch
import open_clip

# Disable Pillow decompression bomb protection
Image.MAX_IMAGE_PIXELS = None

SOURCE_DIR = os.environ["SOURCE_DIR"]

# --- CLIP model ------------------------------------------------------------

device = "cuda" if torch.cuda.is_available() else "cpu"
model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32", pretrained="openai"
)
model.to(device)
model.eval()

# --- helpers ---------------------------------------------------------------

def normalize_exif_value(value):
    if value is None:
        return None
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            return float(value.numerator) / float(value.denominator)
        except Exception:
            return str(value)
    if isinstance(value, tuple) and len(value) == 2:
        try:
            return float(value[0]) / float(value[1])
        except Exception:
            return f"{value[0]}/{value[1]}"
    if value == "":
        return None
    return value


def clean_str(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def extract_exif(path):
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
    def get(tag):
        return exif.get(tag)

    aperture = get("FNumber")
    if isinstance(aperture, (int, float)):
        aperture = round(aperture, 2)

    shutter = get("ExposureTime")
    if isinstance(shutter, float):
        shutter = f"{Fraction(shutter).limit_denominator()}"

    focal = get("FocalLength")
    if isinstance(focal, (int, float)):
        focal = f"{focal:.1f} mm"

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


def compute_clip_embedding(path):
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    image_input = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = model.encode_image(image_input)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb[0].cpu().tolist()  # 512-d list[float]


# --- main ------------------------------------------------------------------

BATCH_SIZE = 1000
pending = 0

with psycopg.connect() as conn:
    register_vector(conn)
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
            embedding = compute_clip_embedding(full_path)

            cur.execute(
                """
                UPDATE photos
                SET file_size     = %s,
                    aperture      = %s,
                    shutter_speed = %s,
                    iso           = %s,
                    focal_length  = %s,
                    date_taken    = %s,
                    camera_model  = %s,
                    lens_model    = %s,
                    width         = %s,
                    height        = %s,
                    embedding     = %s,
                    analysis_date = NOW(),
                    updated_at    = NOW()
                WHERE pathname    = %s
                """,
                (
                    file_size,
                    clean_str(parsed["aperture"]),
                    clean_str(parsed["shutter_speed"]),
                    parsed["iso"],
                    clean_str(parsed["focal_length"]),
                    parsed["date_taken"],
                    clean_str(parsed["camera_model"]),
                    clean_str(parsed["lens_model"]),
                    width,
                    height,
                    embedding,
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

print("EXIF + CLIP embedding extraction complete.")
