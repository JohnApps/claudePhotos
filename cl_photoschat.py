"""
cl_photoschat.py — Streamlit photo search & display app for the photoschat database.

Connects to a PostgreSQL 18 database on MINI from the WINNIESACERPC client.
All search filters use ILIKE for case-insensitive matching.
Face-similarity search uses pgvector cosine distance on 512-d embeddings.
"""

import io
import os
import sys
import base64
import struct
from pathlib import Path, PureWindowsPath
from datetime import date

import streamlit as st
import psycopg
from psycopg.rows import dict_row
from PIL import Image
import numpy as np
import cv2
import insightface
from insightface.app import FaceAnalysis


# ── Configuration ────────────────────────────────────────────────────────────

PAGE_TITLE = "PhotosChat Browser"
PHOTOS_PER_ROW = 3
DEFAULT_ROWS = 3
MAX_ROWS = 20
FACE_EMBEDDING_DIM = 512
THUMBNAIL_MAX_PX = 600  # resize for faster transfer over LAN


# ── Database helpers ─────────────────────────────────────────────────────────

def get_connection_string() -> str:
    """Build a libpq connection string from standard PG env vars."""
    params = {
        "dbname":   os.environ.get("PGDATABASE", "photoschat"),
        "host":     os.environ.get("PGHOST", "MINI"),
        "user":     os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }
    return " ".join(f"{k}={v}" for k, v in params.items() if v)


@st.cache_resource
def get_db_connection():
    """Return a long-lived psycopg connection (cached across reruns)."""
    conn = psycopg.connect(get_connection_string(), row_factory=dict_row)
    conn.autocommit = True
    return conn


def close_connection():
    """Cleanly close the cached DB connection and stop the app."""
    try:
        conn = get_db_connection()
        conn.close()
    except Exception:
        pass
    get_db_connection.clear()
    st.success("Database connection closed. You may close this tab.")
    st.stop()


# ── Query builder ────────────────────────────────────────────────────────────

def build_search_query(filters: dict, tsquery: str | None,
                       limit: int) -> tuple[str, list]:
    """
    Build a parameterised SELECT from the photos table.
    Returns (sql, params).
    """
    clauses: list[str] = []
    params: list = []
    idx = 1  # psycopg uses $1, $2 … but we use %s positional

    for col, val in filters.items():
        if val:
            clauses.append(f"{col}::text ILIKE %s")
            params.append(f"%{val}%")

    if tsquery:
        clauses.append("analysis_tags @@ plainto_tsquery('simple', %s)")
        params.append(tsquery)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT pathname, filename, file_size, aperture, shutter_speed,
               iso, focal_length, date_taken, camera_model, lens_model,
               width, height, caption, gps_lat, gps_lon
        FROM photos
        {where}
        ORDER BY date_taken DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)
    return sql, params


# ── Face-similarity search ───────────────────────────────────────────────────

@st.cache_resource
def get_face_analyzer():
    """
    Load the InsightFace buffalo_l model once and cache it.
    buffalo_l produces 512-d ArcFace embeddings matching the DB schema.
    The model files are downloaded automatically on first run to ~/.insightface.
    """
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def extract_face_embedding(conn, image_bytes: bytes) -> np.ndarray | None:
    """
    Detect the largest face in the uploaded image and return its
    512-d ArcFace embedding vector.  Returns None if no face is found.
    """
    try:
        analyzer = get_face_analyzer()
    except Exception as e:
        st.error(
            f"Failed to load InsightFace model: {e}\n\n"
            "Make sure `insightface` and `onnxruntime` are installed."
        )
        return None

    # Decode image bytes → OpenCV BGR array (InsightFace expects BGR)
    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img_bgr = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img_bgr is None:
        st.error("Could not decode the uploaded image.")
        return None

    faces = analyzer.get(img_bgr)
    if not faces:
        return None

    # Pick the largest detected face (by bounding-box area)
    largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return largest.embedding  # numpy array, shape (512,)


def find_similar_faces(conn, embedding: np.ndarray, limit: int = 30):
    """
    Query photo_faces for nearest neighbours by cosine distance.
    """
    vec_literal = "[" + ",".join(str(float(v)) for v in embedding) + "]"
    sql = """
        SELECT pf.photo_path AS pathname,
               pf.bbox,
               pf.embedding <=> %s::vector AS distance
        FROM photo_faces pf
        ORDER BY distance
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [vec_literal, limit])
        return cur.fetchall()


# ── Image loading ────────────────────────────────────────────────────────────

def load_photo_bytes(pathname: str) -> bytes | None:
    """Read a photo file from the network path and return raw bytes."""
    try:
        p = Path(pathname)
        if not p.exists():
            return None
        return p.read_bytes()
    except Exception:
        return None


def photo_to_base64_thumb(raw: bytes, max_px: int = THUMBNAIL_MAX_PX) -> str:
    """Resize to thumbnail and return a base64-encoded JPEG string."""
    img = Image.open(io.BytesIO(raw))
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


# ── UI components ────────────────────────────────────────────────────────────

def render_sidebar() -> tuple[dict, str | None, int, bytes | None]:
    """
    Draw sidebar controls and return
    (filter_dict, tsquery_text, num_rows, face_image_bytes).
    """
    with st.sidebar:
        st.header("Search Filters")

        filters = {}
        filters["pathname"]     = st.text_input("Pathname")
        filters["aperture"]     = st.text_input("Aperture")
        filters["shutter_speed"] = st.text_input("Shutter Speed")
        filters["iso"]          = st.text_input("ISO")
        filters["focal_length"] = st.text_input("Focal Length")
        filters["camera_model"] = st.text_input("Camera Model")
        filters["lens_model"]   = st.text_input("Lens Model")
        filters["caption"]      = st.text_input("Caption")

        col_a, col_b = st.columns(2)
        with col_a:
            date_from = st.date_input("Date from", value=None)
        with col_b:
            date_to = st.date_input("Date to", value=None)

        # Date range handled separately (not ILIKE)
        date_range = (date_from, date_to)

        st.divider()
        tsquery = st.text_input("Full-text tag search (analysis_tags)")

        st.divider()
        num_rows = st.slider("Rows to display", 1, MAX_ROWS, DEFAULT_ROWS)

        st.divider()
        st.subheader("Face Similarity Search")
        face_file = st.file_uploader(
            "Upload or paste a face image",
            type=["jpg", "jpeg", "png", "webp"],
        )
        face_bytes = face_file.read() if face_file else None

        st.divider()
        if st.button("🔌  Close Connection", type="primary"):
            close_connection()

    # Strip empty filter values
    filters = {k: v.strip() for k, v in filters.items() if v and v.strip()}

    # Merge date range into filters dict as special keys
    if date_from:
        filters["_date_from"] = date_from
    if date_to:
        filters["_date_to"] = date_to

    return filters, (tsquery.strip() if tsquery else None), num_rows, face_bytes


def build_full_query(filters: dict, tsquery: str | None,
                     limit: int) -> tuple[str, list]:
    """
    Extended query builder that also handles date-range filters.
    """
    clauses: list[str] = []
    params: list = []

    # Date range (special keys)
    date_from = filters.pop("_date_from", None)
    date_to = filters.pop("_date_to", None)

    for col, val in filters.items():
        clauses.append(f"{col}::text ILIKE %s")
        params.append(f"%{val}%")

    if date_from:
        clauses.append("date_taken >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("date_taken <= %s")
        params.append(date_to)

    if tsquery:
        clauses.append("analysis_tags @@ plainto_tsquery('simple', %s)")
        params.append(tsquery)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT pathname, filename, file_size, aperture, shutter_speed,
               iso, focal_length, date_taken, camera_model, lens_model,
               width, height, caption, gps_lat, gps_lon
        FROM photos
        {where}
        ORDER BY date_taken DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)
    return sql, params


def render_photo_grid(rows: list[dict], num_rows: int):
    """Display photos in a 3-column grid with full-screen modal support."""
    if not rows:
        st.info("No photos match the current filters.")
        return

    st.caption(f"Showing {len(rows)} photo(s)")

    for row_idx in range(0, len(rows), PHOTOS_PER_ROW):
        cols = st.columns(PHOTOS_PER_ROW)
        for col_idx, col in enumerate(cols):
            photo_idx = row_idx + col_idx
            if photo_idx >= len(rows):
                break
            photo = rows[photo_idx]
            with col:
                render_single_photo(photo, photo_idx)


@st.dialog("Full Size Photo", width="large")
def show_fullsize_dialog(pathname: str, caption: str | None):
    """Modal dialog that renders the photo at full available width."""
    raw = load_photo_bytes(pathname)
    if raw:
        st.image(raw, width="stretch")
    else:
        st.warning(f"Cannot load:\n{pathname}")
    if caption:
        st.write(caption)
    st.code(pathname, language=None)


def render_single_photo(photo: dict, idx: int):
    """Render one photo card with thumbnail and metadata."""
    raw = load_photo_bytes(photo["pathname"])
    if raw:
        thumb_b64 = photo_to_base64_thumb(raw)
        st.image(
            f"data:image/jpeg;base64,{thumb_b64}",
            width="stretch",
        )
    else:
        st.warning(f"Cannot load:\n{photo['pathname']}")

    # Metadata caption
    parts = []
    if photo.get("camera_model"):
        parts.append(photo["camera_model"])
    if photo.get("lens_model"):
        parts.append(photo["lens_model"])
    if photo.get("aperture"):
        parts.append(f"f/{photo['aperture']}")
    if photo.get("shutter_speed"):
        parts.append(photo["shutter_speed"])
    if photo.get("iso"):
        parts.append(f"ISO {photo['iso']}")
    if photo.get("date_taken"):
        parts.append(str(photo["date_taken"])[:10])
    st.caption(" · ".join(parts) if parts else "")

    # Full-size button opens a wide modal dialog
    if st.button("🔍 View full size", key=f"fullsize_{idx}"):
        show_fullsize_dialog(photo["pathname"], photo.get("caption"))


def render_face_results(conn, face_bytes: bytes, num_rows: int):
    """Run face similarity search and render results."""
    st.subheader("Face Similarity Results")

    with st.spinner("Detecting face and computing embedding…"):
        embedding = extract_face_embedding(conn, face_bytes)

    if embedding is None:
        st.warning("No face detected in the uploaded image. Try a clearer photo.")
        return

    results = find_similar_faces(conn, embedding, limit=num_rows * PHOTOS_PER_ROW)
    if not results:
        st.info("No similar faces found in the database.")
        return

    st.caption(
        f"Found {len(results)} match(es) — "
        f"closest distance: {results[0]['distance']:.4f}"
    )

    # Convert to photo-grid format
    grid_rows = [{"pathname": r["pathname"], **{k: None for k in
                   ["filename","file_size","aperture","shutter_speed",
                    "iso","focal_length","date_taken","camera_model",
                    "lens_model","width","height","caption","gps_lat","gps_lon"]}}
                 for r in results]
    render_photo_grid(grid_rows, num_rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title=PAGE_TITLE,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title(PAGE_TITLE)

    # Connect
    try:
        conn = get_db_connection()
    except Exception as e:
        st.error(f"Cannot connect to database: {e}")
        st.stop()

    # Sidebar
    filters, tsquery, num_rows, face_bytes = render_sidebar()
    limit = num_rows * PHOTOS_PER_ROW

    # Face search mode
    if face_bytes:
        render_face_results(conn, face_bytes, num_rows)
        return

    # Standard search
    sql, params = build_full_query(filters, tsquery, limit)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception as e:
        st.error(f"Query error: {e}")
        rows = []

    render_photo_grid(rows, num_rows)


if __name__ == "__main__":
    main()
