"""
cl_photoschat.py — Streamlit photo search & display app for the photoschat database.

Connects to a PostgreSQL 18 database on MINI from the WINNIESACERPC client.
All search filters use ILIKE for case-insensitive matching.
Face-similarity search uses pgvector cosine distance on face_embedding (512-d, InsightFace).
Image-similarity search uses pgvector cosine distance on embedding (512-d, CLIP ViT-B/32).
"""

import io
import os
import sys
import base64
import struct
import warnings
from pathlib import Path, PureWindowsPath
from datetime import date

# Suppress FutureWarning from InsightFace's use of deprecated scikit-image API
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")

import streamlit as st
import psycopg
from psycopg.rows import dict_row
from PIL import Image
import numpy as np
import cv2
import torch
import clip
import insightface
from insightface.app import FaceAnalysis


# ── Configuration ────────────────────────────────────────────────────────────

PAGE_TITLE = "PhotosChat Browser"
PHOTOS_PER_ROW = 3
DEFAULT_ROWS = 3
MAX_ROWS = 100
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


# ── CLIP image-similarity search ─────────────────────────────────────────────

@st.cache_resource
def get_clip_model():
    """Load CLIP ViT-B/32 once and cache. Returns (model, preprocess)."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device)
    model.eval()
    return model, preprocess, device


def extract_image_embedding(image_bytes: bytes) -> np.ndarray | None:
    """Compute a 512-d CLIP embedding from raw image bytes."""
    try:
        model, preprocess, device = get_clip_model()
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = preprocess(img).unsqueeze(0).to(device)
        with torch.no_grad():
            emb = model.encode_image(tensor)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.squeeze().cpu().numpy()
    except Exception as e:
        st.error(f"CLIP embedding error: {e}")
        return None


def find_similar_images(conn, embedding: np.ndarray, limit: int = 30):
    """Query photos for nearest neighbours by cosine distance on embedding."""
    vec_literal = "[" + ",".join(str(float(v)) for v in embedding) + "]"
    sql = """
        SELECT pathname, filename, file_size, aperture, shutter_speed,
               iso, focal_length, date_taken, camera_model, lens_model,
               width, height, caption, gps_lat, gps_lon,
               embedding <=> %s::vector AS distance
        FROM photos
        WHERE embedding IS NOT NULL
        ORDER BY distance
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [vec_literal, limit])
        return cur.fetchall()


# ── Face-similarity search ───────────────────────────────────────────────────

@st.cache_resource
def get_face_analyzer():
    """
    Load the InsightFace buffalo_l model once and cache it.
    buffalo_l produces 512-d ArcFace embeddings matching the DB schema.
    """
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def extract_face_embedding(image_bytes: bytes) -> np.ndarray | None:
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

    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    img_bgr = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img_bgr is None:
        st.error("Could not decode the uploaded image.")
        return None

    faces = analyzer.get(img_bgr)
    if not faces:
        return None

    largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return largest.embedding


def find_similar_faces(conn, embedding: np.ndarray, limit: int = 30):
    """Query photos for nearest neighbours by cosine distance on face_embedding."""
    vec_literal = "[" + ",".join(str(float(v)) for v in embedding) + "]"
    sql = """
        SELECT pathname, filename, file_size, aperture, shutter_speed,
               iso, focal_length, date_taken, camera_model, lens_model,
               width, height, caption, gps_lat, gps_lon,
               face_embedding <=> %s::vector AS distance
        FROM photos
        WHERE face_embedding IS NOT NULL
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

def render_sidebar() -> tuple[dict, str | None, int, bytes | None, bytes | None]:
    """
    Draw sidebar controls and return
    (filter_dict, tsquery_text, num_rows, face_image_bytes, image_sim_bytes).
    """
    with st.sidebar:
        st.header("Search Filters")

        filters = {}
        filters["pathname"]      = st.text_input("Pathname")
        filters["aperture"]      = st.text_input("Aperture")
        filters["shutter_speed"] = st.text_input("Shutter Speed")
        filters["iso"]           = st.text_input("ISO")
        filters["focal_length"]  = st.text_input("Focal Length")
        filters["camera_model"]  = st.text_input("Camera Model")
        filters["lens_model"]    = st.text_input("Lens Model")
        filters["caption"]       = st.text_input("Caption")

        col_a, col_b = st.columns(2)
        with col_a:
            date_from = st.date_input("Date from", value=None)
        with col_b:
            date_to = st.date_input("Date to", value=None)

        st.divider()
        tsquery = st.text_input("Full-text tag search (analysis_tags)")
        st.caption("Comma = OR, Space = AND. E.g.: `beach, car` or `beach tree`")

        st.divider()
        num_rows = st.slider("Rows to display", 1, MAX_ROWS, DEFAULT_ROWS)

        st.divider()
        st.subheader("🖼️ Similar Image Search")
        st.caption("Uses CLIP ViT-B/32 embeddings")
        image_sim_file = st.file_uploader(
            "Upload a reference image",
            type=["jpg", "jpeg", "png", "webp"],
            key="image_similarity",
        )
        image_sim_bytes = image_sim_file.read() if image_sim_file else None

        st.divider()
        st.subheader("👤 Face Similarity Search")
        st.caption("Uses InsightFace ArcFace embeddings")
        face_file = st.file_uploader(
            "Upload a face image",
            type=["jpg", "jpeg", "png", "webp"],
            key="face_similarity",
        )
        face_bytes = face_file.read() if face_file else None

        st.divider()
        if st.button("🔌  Close Connection", type="primary"):
            close_connection()

    # Strip empty filter values
    filters = {k: v.strip() for k, v in filters.items() if v and v.strip()}

    if date_from:
        filters["_date_from"] = date_from
    if date_to:
        filters["_date_to"] = date_to

    return filters, (tsquery.strip() if tsquery else None), num_rows, face_bytes, image_sim_bytes


def build_full_query(filters: dict, tsquery: str | None,
                     limit: int) -> tuple[str, list]:
    """Extended query builder that also handles date-range filters."""
    clauses: list[str] = []
    params: list = []

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
        # Parse user input: comma = OR, space = AND
        # E.g., "beach, car" → "beach | car"
        # E.g., "beach tree" → "beach & tree"
        # E.g., "beach tree, car person" → "(beach & tree) | (car & person)"
        or_groups = [g.strip() for g in tsquery.split(",") if g.strip()]
        tsquery_parts = []
        for group in or_groups:
            terms = [t.strip() for t in group.split() if t.strip()]
            if terms:
                # Join terms within a group with AND
                tsquery_parts.append(" & ".join(terms))
        if tsquery_parts:
            # Join groups with OR
            final_tsquery = " | ".join(f"({p})" if " & " in p else p for p in tsquery_parts)
            clauses.append("analysis_tags @@ to_tsquery('simple', %s)")
            params.append(final_tsquery)

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
    """Render one photo card with thumbnail, caption, and metadata."""
    raw = load_photo_bytes(photo["pathname"])
    if raw:
        thumb_b64 = photo_to_base64_thumb(raw)
        st.image(
            f"data:image/jpeg;base64,{thumb_b64}",
            width="stretch",
        )
    else:
        st.warning(f"Cannot load:\n{photo['pathname']}")

    # Display caption below the photo
    if photo.get("caption"):
        st.markdown(f"**{photo['caption']}**")

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

    # Show distance if present (similarity search results)
    if photo.get("distance") is not None:
        parts.append(f"dist: {photo['distance']:.4f}")

    st.caption(" · ".join(parts) if parts else "")

    if st.button("🔍 View full size", key=f"fullsize_{idx}"):
        show_fullsize_dialog(photo["pathname"], photo.get("caption"))


def render_image_similarity_results(conn, image_bytes: bytes, num_rows: int):
    """Run CLIP image similarity search and render results."""
    st.subheader("🖼️ Similar Image Results")

    with st.spinner("Computing CLIP embedding…"):
        embedding = extract_image_embedding(image_bytes)

    if embedding is None:
        st.warning("Could not compute an embedding for the uploaded image.")
        return

    results = find_similar_images(conn, embedding, limit=num_rows * PHOTOS_PER_ROW)
    if not results:
        st.info("No similar images found in the database.")
        return

    st.caption(
        f"Found {len(results)} match(es) — "
        f"closest distance: {results[0]['distance']:.4f}"
    )
    render_photo_grid(results, num_rows)


def render_face_results(conn, face_bytes: bytes, num_rows: int):
    """Run face similarity search and render results."""
    st.subheader("👤 Face Similarity Results")

    with st.spinner("Detecting face and computing embedding…"):
        embedding = extract_face_embedding(face_bytes)

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
    render_photo_grid(results, num_rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title=PAGE_TITLE,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title(PAGE_TITLE)

    try:
        conn = get_db_connection()
    except Exception as e:
        st.error(f"Cannot connect to database: {e}")
        st.stop()

    filters, tsquery, num_rows, face_bytes, image_sim_bytes = render_sidebar()
    limit = num_rows * PHOTOS_PER_ROW

    # Image similarity mode (CLIP)
    if image_sim_bytes:
        render_image_similarity_results(conn, image_sim_bytes, num_rows)
        return

    # Face similarity mode (InsightFace)
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
