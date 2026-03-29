# cl_update_exif.py
import os
import re
from PIL import Image
from PIL.ExifTags import TAGS
from pathlib import Path
from datetime import datetime
import psycopg

Image.MAX_IMAGE_PIXELS = None


def sanitize(value):
    """Replace null bytes in string values."""
    if isinstance(value, str):
        return value.replace("\x00", " ")
    return value


def get_exif(path: str) -> dict:
    """Extract relevant EXIF fields from a JPEG."""
    data = {"file_size": Path(path).stat().st_size}
    try:
        img = Image.open(path)
        exif_raw = img._getexif()
        if not exif_raw:
            return data
        exif = {TAGS.get(k, k): v for k, v in exif_raw.items()}

        fn = exif.get("FNumber")
        if fn:
            val = f"f/{fn[0] / fn[1]:.1f}" if isinstance(fn, tuple) else f"f/{fn}"
            data["aperture"] = sanitize(val)

        et = exif.get("ExposureTime")
        if et:
            if isinstance(et, tuple):
                n, d = et
                val = f"{n}/{d}" if d != 1 else f"{n}"
            else:
                val = str(et)
            data["shutter_speed"] = sanitize(val)

        iso = exif.get("ISOSpeedRatings")
        if iso:
            data["iso"] = int(iso[0]) if isinstance(iso, tuple) else int(iso)

        fl = exif.get("FocalLength")
        if fl:
            mm = fl[0] / fl[1] if isinstance(fl, tuple) else fl
            data["focal_length"] = sanitize(f"{mm:.1f}mm")

        dt = exif.get("DateTimeOriginal") or exif.get("DateTime")
        if dt:
            dt = sanitize(dt)
            data["date_taken"] = datetime.strptime(dt, "%Y:%m:%d %H:%M:%S")

        model = exif.get("Model")
        if model:
            data["camera_model"] = sanitize(model)

        lens = exif.get("LensModel")
        if lens:
            data["lens_model"] = sanitize(lens)

    except Exception as e:
        print(f"  EXIF error for {path}: {e}")
    return data


def main():
    BATCH_SIZE = 1000

    conninfo = psycopg.conninfo.make_conninfo(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )

    conn = psycopg.connect(conninfo, autocommit=False)

    rows = conn.execute(
        "SELECT pathname FROM photos WHERE pathname ILIKE '%.jpg' OR pathname ILIKE '%.jpeg'"
    ).fetchall()

    print(f"Found {len(rows)} JPEG paths in photos table.")

    update_sql = """
        UPDATE photos
        SET file_size     = %(file_size)s,
            aperture      = %(aperture)s,
            shutter_speed = %(shutter_speed)s,
            iso           = %(iso)s,
            focal_length  = %(focal_length)s,
            date_taken    = %(date_taken)s,
            camera_model  = %(camera_model)s,
            lens_model    = %(lens_model)s
        WHERE pathname    = %(pathname)s
    """

    cols = ("file_size", "aperture", "shutter_speed", "iso",
            "focal_length", "date_taken", "camera_model", "lens_model")

    updated = 0
    batch_count = 0

    conn.execute("BEGIN")

    for (pathname,) in rows:
        pathname = sanitize(pathname)

        if not Path(pathname).is_file():
            print(f"  SKIP (missing): {pathname}")
            continue

        exif = get_exif(pathname)
        if not exif:
            print(f"  SKIP (no EXIF): {pathname}")
            continue

        exif["pathname"] = pathname
        for col in cols:
            exif.setdefault(col, None)

        conn.execute(update_sql, exif)
        updated += 1
        batch_count += 1

        if batch_count >= BATCH_SIZE:
            conn.execute("COMMIT")
            print(f"  Committed batch ({updated} total so far)")
            conn.execute("BEGIN")
            batch_count = 0

    # commit remaining
    conn.execute("COMMIT")
    print(f"Done. Updated {updated}/{len(rows)} rows.")

    conn.close()


if __name__ == "__main__":
    main()