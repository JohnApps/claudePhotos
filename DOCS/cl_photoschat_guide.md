# PhotosChat Browser — Implementation & Operating Guide

## 1  Overview

`cl_photoschat.py` is a Streamlit application that searches and displays photos
stored in the **photoschat** PostgreSQL 18 database.  The UI runs on
**WINNIESACERPC** (4 cores / 32 GB) and queries the database on **MINI**
(16 cores / 32 GB) over a 1 Gbps Ethernet link.

## 2  Architecture

```
WINNIESACERPC                          MINI
┌──────────────────────┐     1 Gbps    ┌─────────────────────┐
│  Streamlit UI        │◄────────────►│  PostgreSQL 18.1     │
│  (cl_photoschat.py)  │   TCP 5432   │  DB: photoschat      │
│  Python 3.14 / Conda │              │  pgvector + pg_trgm  │
│  reads photos from   │              └─────────────────────┘
│  O:\Bilder (local)   │
└──────────────────────┘
```

Photos are read directly from the filesystem paths stored in the `pathname`
column; no image data lives in PostgreSQL.

## 3  Directory Layout

```
H:\claude\                     ← ROOT_DIR
├── cl_photoschat.py           ← main Streamlit app
├── requirements.txt
├── .gitignore
├── SQL\                       ← SQL_DIR
│   └── cl_optimizations.sql   ← recommended DB optimisations
└── DOCS\                      ← DOCS_DIR
    └── (this file)
```

## 4  Prerequisites

| Component        | Version required      |
|------------------|-----------------------|
| Conda            | 26.1.1+               |
| Python           | 3.14.x (Anaconda)     |
| PostgreSQL       | 18.1 (on MINI)        |
| pgvector         | latest (extension)    |
| pg_trgm          | bundled with PG 18    |
| Windows          | 10.0.26200+           |

## 5  Installation

```powershell
# On WINNIESACERPC
cd H:\claude

# Create and activate conda environment
conda create -n photoschat python=3.14 -y
conda activate photoschat

# Install Python dependencies
pip install -r requirements.txt

# Set PostgreSQL environment variables (add to your profile or .env)
set PGDATABASE=photoschat
set PGHOST=MINI
set PGUSER=postgres
set PGPASSWORD=<your_password>
```

## 6  Running the Application

```powershell
cd H:\claude
conda activate photoschat
streamlit run cl_photoschat.py
```

The browser opens automatically at `http://localhost:8501`.

## 7  Using the Application

### 7.1  Searching Photos

The left sidebar contains all search fields.  Every text field uses
**case-insensitive partial matching** (ILIKE `%term%`) so you can type
any substring.

| Field                | What it searches                          |
|----------------------|-------------------------------------------|
| Pathname             | Full file path (O:\Bilder\…)              |
| Aperture             | e.g. "2.8"                                |
| Shutter Speed        | e.g. "1/250"                              |
| ISO                  | e.g. "800"                                |
| Focal Length          | e.g. "50"                                 |
| Camera Model         | e.g. "Nikon", "Canon EOS"                 |
| Lens Model           | e.g. "70-200"                             |
| Caption              | AI-generated caption text                 |
| Date from / Date to  | Date-taken range filter                   |
| Full-text tag search  | Searches the `analysis_tags` tsvector     |

### 7.2  Viewing Photos

Photos are displayed **3 per row**.  Use the **Rows to display** slider
(1–20) to control how many rows appear.

Click **"View full size"** beneath any thumbnail to expand it.  The full
pathname is shown at the bottom of the expanded view.

### 7.3  Face Similarity Search

Upload a face image via the sidebar file uploader.  The app detects the
largest face in the image using InsightFace's `buffalo_l` model, extracts
a 512-dimensional ArcFace embedding, then queries `photo_faces` for the
nearest neighbours by cosine distance.

On first run, InsightFace automatically downloads the model files (~300 MB)
to `~/.insightface/models/buffalo_l/`.  Subsequent runs load from cache.

If no face is detected, try a clearer or larger image of the face.

### 7.4  Closing the Connection

Click the **🔌 Close Connection** button in the sidebar to cleanly shut
down the database connection before closing the browser tab.

## 8  Database Optimisations

The file `SQL\cl_optimizations.sql` contains recommended changes.
Run it on MINI:

```powershell
psql -h MINI -U postgres -d photoschat -f SQL\cl_optimizations.sql
```

Key recommendations:

1. **Add trigram (GIN) indexes** on every column searched via ILIKE —
   `pathname`, `aperture`, `shutter_speed`, `focal_length`, `camera_model`,
   `lens_model`.  Without these, ILIKE forces sequential scans.

2. **Replace IVFFlat with HNSW** for the `face_embedding` index.  HNSW
   delivers higher recall and doesn't require periodic re-clustering as
   data grows.

3. **Remove the duplicate vector index** — `photos_embedding_idx` (IVFFlat)
   duplicates `idx_photos_embedding` (HNSW) on the same column.

4. **Add an HNSW index to `photo_faces.embedding`** — currently unindexed,
   meaning every similarity search is a sequential scan.

5. **Tune `postgresql.conf`** on MINI for 32 GB RAM:
   `shared_buffers = 8GB`, `effective_cache_size = 24GB`,
   `work_mem = 64MB`, `random_page_cost = 1.1`.

6. **Deploy PgBouncer** on MINI in transaction mode to pool connections
   efficiently with 16 cores.

## 9  Git Setup

```powershell
cd H:\claude
git init
git add .
git commit -m "Initial commit: PhotosChat Browser"
```

The `.gitignore` excludes Python caches, virtual environments, IDE files,
secrets, and OS artefacts.

## 10  Troubleshooting

| Symptom                         | Fix                                          |
|---------------------------------|----------------------------------------------|
| "Cannot connect to database"    | Check PGHOST, PGUSER, PGPASSWORD env vars    |
| Photos show "Cannot load"       | Verify O:\Bilder is mapped and accessible     |
| Slow ILIKE searches             | Run `cl_optimizations.sql` on MINI            |
| Face search says "not configured" | Integrate an embedding model — see §7.3     |
| Port 8501 already in use        | `streamlit run cl_photoschat.py --server.port 8502` |

## 11  Dependencies

See `requirements.txt`.  All libraries are current, non-deprecated versions:

- **streamlit** ≥ 1.45 — UI framework
- **psycopg[binary]** ≥ 3.2 — PostgreSQL 18 driver (psycopg 3)
- **Pillow** ≥ 11.0 — image loading and thumbnailing
- **numpy** ≥ 2.1 — array handling for embeddings
- **opencv-python** ≥ 4.10 — image decoding for InsightFace
- **insightface** ≥ 0.7.3 — face detection and ArcFace embedding (buffalo_l)
- **onnxruntime** ≥ 1.19 — ONNX inference backend for InsightFace
