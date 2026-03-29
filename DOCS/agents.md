# Agents Guide - PhotosChat Browser

## Quick Start for Agents

When working on this project, follow these patterns:

### 1. File Naming Convention
All application files use the `cl_` prefix:
- `cl_photoschat_embedding.py` - Main application with CLIP and face search
- `cl_photoschat.py` - Original version (if present)

### 2. Before Making Changes
- Always read the current file state before editing
- The main application file is `cl_photoschat_embedding.py`
- User uploads are read-only at `/mnt/user-data/uploads/` — copy to `/home/claude/` to edit
- Final outputs go to `/mnt/user-data/outputs/`

### 3. Common Modification Patterns

#### Adding New Sidebar Filters
Add to the `render_sidebar()` function in the filters dict:
```python
filters["new_column"] = st.text_input("Display Label")
```
The `build_full_query()` function automatically handles ILIKE matching.

#### Adding New Photo Metadata Display
Modify `render_single_photo()` — add to the `parts` list:
```python
if photo.get("new_field"):
    parts.append(f"label: {photo['new_field']}")
```

#### Changing Grid Layout
Adjust these constants:
```python
PHOTOS_PER_ROW = 3   # Columns per row
MAX_ROWS = 100       # Maximum rows in slider
DEFAULT_ROWS = 3     # Initial slider value
```

### 4. Testing Considerations

The app connects to PostgreSQL on host `MINI`. Without access to that server, you cannot run the app locally. Changes should be syntactically validated but full testing requires the user's environment.

### 5. Dependencies

Required packages (install with `--break-system-packages` flag for pip):
- streamlit
- psycopg (v3, not psycopg2)
- pgvector
- torch
- clip (OpenAI CLIP)
- insightface
- opencv-python
- onnxruntime
- Pillow
- numpy

## Issues Encountered and Resolutions

### Issue: InsightFace Deprecation Warning
**Symptom:** 
```
FutureWarning: `estimate` is deprecated since version 0.26 and will be removed in version 2.2
```

**Cause:** InsightFace uses scikit-image's `SimilarityTransform.estimate()` which is deprecated.

**Resolution:** Add warning filter before importing insightface:
```python
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")
```

**Why this works:** The warning originates in InsightFace's internal code, not user code. Suppressing it is safe until InsightFace updates their implementation.

### Issue: Read-Only Upload Directory
**Symptom:** `Cannot edit file: This file is in a read-only directory`

**Resolution:** Copy file to working directory before editing:
```bash
cp /mnt/user-data/uploads/file.py /home/claude/file.py
# ... make edits ...
cp /home/claude/file.py /mnt/user-data/outputs/file.py
```

### Issue: Streamlit use_container_width Deprecation
**Symptom:** Deprecation warning for `use_container_width=True/False`

**Resolution:** Use `width="stretch"` or `width="content"` instead.

## Architecture Notes

### Search Flow
```
User Input → render_sidebar()
    ↓
Mode Selection in main():
    ├─ image_sim_bytes? → render_image_similarity_results() → CLIP embedding → pgvector query
    ├─ face_bytes?      → render_face_results()             → ArcFace embedding → pgvector query  
    └─ else             → build_full_query()                → Standard SQL with ILIKE
    ↓
render_photo_grid() → render_single_photo() for each result
```

### Embedding Consistency
Critical: Database embeddings must be generated with the same models used at query time:
- CLIP: ViT-B/32 → 512-d embedding in `embedding` column
- Face: buffalo_l ArcFace → 512-d embedding in `face_embedding` column

Mismatched models will produce meaningless similarity results.

## User Preferences

- **Communication:** Terse, directive instructions. Don't ask for clarification unless truly ambiguous.
- **Deliverables:** Complete updated files, not diffs or patches.
- **Iteration:** Expect multiple correction cycles based on runtime behavior.
