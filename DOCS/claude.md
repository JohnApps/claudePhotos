# PhotosChat Browser - Claude Context

## Project Overview

PhotosChat Browser is a Streamlit-based photo management and search application that connects to a PostgreSQL 18 database (`photoschat`). It supports rich photo discovery through metadata filtering, full-text search, and AI-powered similarity search using CLIP and InsightFace embeddings.

## Repository

```bash
git remote add origin https://github.com/JohnApps/claudePhotos.git
```

## Operating Environment

**Platform:** Windows 11 (exclusively)

All code runs on Windows 11. Use Windows-compatible paths, libraries, and patterns. No Linux/macOS-specific code.

## Development Guidelines

### Use Latest Versions
- Always use the latest stable versions of libraries and frameworks
- Prefer modern APIs over legacy ones (e.g., psycopg v3 over psycopg2)
- Check for and adopt newer, better approaches when available

### Avoid Deprecated Software
- Do not use deprecated functions, methods, or libraries
- When deprecation warnings appear, update to the recommended replacement immediately
- Examples of deprecations to avoid:
  - `use_container_width` in Streamlit → use `width="stretch"` or `width="content"`
  - `psycopg2` → use `psycopg` (v3)
  - `SimilarityTransform.estimate()` in scikit-image → use `SimilarityTransform.from_estimate()`
- If a dependency uses deprecated code internally (like InsightFace), suppress warnings until the library updates

## Technical Stack

| Component | Technology |
|-----------|------------|
| OS | Windows 11 |
| Frontend | Streamlit (Python), `cl_` filename prefix convention |
| Python | 3.14 in Conda environment |
| Database | PostgreSQL 18 with pgvector extension |
| DB Driver | psycopg v3 (NOT psycopg2) |
| AI/ML | CLIP ViT-B/32 (image embeddings), InsightFace buffalo_l ArcFace (face embeddings) |
| Infrastructure | PostgreSQL on MINI, accessed from WINNIESACERPC over 1 Gbps Ethernet |

## Database Schema (photos table)

### Core Columns
- `pathname` - Full filesystem path to photo
- `filename` - Just the filename
- `caption` - Text caption/description

### EXIF Columns
- `file_size`, `aperture`, `shutter_speed`, `iso`, `focal_length`
- `date_taken`, `camera_model`, `lens_model`
- `width`, `height`

### Spatial Columns
- `gps_lat`, `gps_lon`

### AI/Search Columns
- `analysis_tags` (tsvector) - Full-text search index
- `embedding vector(512)` - CLIP ViT-B/32 image embedding
- `face_embedding vector(512)` - InsightFace ArcFace face embedding

## Key Application Patterns

### Database Connection
```python
@st.cache_resource
def get_db_connection():
    conn = psycopg.connect(get_connection_string(), row_factory=dict_row)
    conn.autocommit = True
    return conn
```

### pgvector Similarity Search
Uses cosine distance operator `<=>` for both CLIP and face embeddings:
```python
sql = """
    SELECT *, embedding <=> %s::vector AS distance
    FROM photos
    WHERE embedding IS NOT NULL
    ORDER BY distance
    LIMIT %s
"""
```

### Caching Resources
Use `@st.cache_resource` for expensive objects:
- Database connections
- CLIP model
- InsightFace FaceAnalysis analyzer

### Photo Grid Display
- 3 photos per row (`PHOTOS_PER_ROW = 3`)
- Configurable rows via slider (1-100)
- Thumbnails resized to 600px max for faster transfer
- Full-size modal via `@st.dialog(width="large")`

## Streamlit API Notes

### Image Display
```python
# Correct (current API)
st.image(img, width="stretch")  # or width="content"

# Deprecated (removal after 2025-12-31)
st.image(img, use_container_width=True)  # DON'T USE
```

### Modal Dialogs
Use `@st.dialog(width="large")` for full-size photo overlays. Avoid `st.expander` inside narrow columns as it constrains image display.

## Common Issues and Solutions

### InsightFace FutureWarning
**Issue:** `FutureWarning: estimate is deprecated since version 0.26` from scikit-image's SimilarityTransform in InsightFace's face_align.py

**Solution:** Add before importing insightface:
```python
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")
```

### Null Bytes in EXIF Data
**Issue:** PostgreSQL rejects `\x00` null bytes in string fields

**Solution:** Sanitize all string inputs by replacing `\x00` with spaces before database insertion.

### Large Image Handling
**Issue:** Pillow may refuse to process very large images

**Solution:** Set `Image.MAX_IMAGE_PIXELS = None` before processing.

## Configuration Constants

```python
PAGE_TITLE = "PhotosChat Browser"
PHOTOS_PER_ROW = 3
DEFAULT_ROWS = 3
MAX_ROWS = 100
FACE_EMBEDDING_DIM = 512
THUMBNAIL_MAX_PX = 600
```

## Search Modes

The application has three mutually exclusive search modes, evaluated in order in `main()`:

1. **CLIP Image Similarity** - Upload reference image → find visually similar photos
2. **Face Similarity** - Upload face image → find photos with similar faces
3. **Standard Filtered Search** - ILIKE filters + full-text search on analysis_tags

## User Communication Style

Joe communicates tersely and directively. Expect:
- Minimal context in requests
- Expectation that you locate and modify correct code sections independently
- Iterative refinement through multiple correction cycles
- Preference for complete updated files rather than diffs
