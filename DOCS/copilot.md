CoPilot Knowledge Base



This document consolidates all relevant technical knowledge, patterns, decisions, and lessons learned from the development of the EXIF + CLIP ingestion pipeline. It is intended as a durable reference for any future agent or developer working inside this repository.



1\. Environment Standards



Windows 11 Compatibility



All tooling, libraries, and scripts must run cleanly on Windows 11. This includes:



Python 3.14.3 or later



Conda 26.1.1 (latest)



GPU acceleration when available (CUDA on supported NVIDIA hardware)



Full support for long file paths



No reliance on deprecated Windows APIs



Python Environment



Use Python 3.14.3+



Avoid deprecated libraries (e.g., psycopg2)



Prefer modern, actively maintained packages:



psycopg (psycopg3)



open\_clip\_torch



pgvector



Pillow



torch



Conda Environment



Conda version: 26.1.1



Environments must pin Python version explicitly



GPU-enabled PyTorch builds should be installed via conda-forge or pytorch channel



2\. PostgreSQL + DuckDB Integration



PostgreSQL



Use psycopg3 exclusively



Connection parameters are read from environment variables:



PGHOST



PGDATABASE



PGUSER



PGPASSWORD



PGPORT



The photos table schema includes:



EXIF metadata fields



CLIP embedding (vector(512), pgvector)



Image dimensions



Analysis timestamps



DuckDB



Used for local metadata staging or analytics



No deprecated extensions



Avoid storing large binary blobs in DuckDB



3\. Image Processing Rules



Pillow Configuration



To safely process large images without triggering DOS bomb warnings:



from PIL import Image

Image.MAX\_IMAGE\_PIXELS = None



This suppresses Pillow's decompression bomb protection, which is necessary for large high-resolution images.



EXIF Extraction



Key rules:



Always normalize EXIF values



Convert IFDRational to floats



Convert rational tuples to floats



Convert empty strings to None



Remove NUL bytes from all strings before inserting into PostgreSQL



Width \& Height



Extracted directly from Pillow:



width, height = img.size



4\. CLIP Embedding Pipeline



Model



Use OpenCLIP ViT-B/32 with openai weights



Embedding dimension: 512



Embeddings must be L2-normalized



GPU Acceleration



Use CUDA when available



Fallback to CPU otherwise



Embedding Storage



Stored in PostgreSQL column:



embedding vector(512)



Requires pgvector extension



5\. Database Update Strategy



Batch Commits



To avoid excessive WAL pressure and improve performance:



Commit every 500 updates



Use a counter to track pending updates



Update Key



All updates are keyed by pathname, not id



Timestamps



analysis\_date and updated\_at are always updated via NOW()



6\. Error Handling Lessons Learned



IFDRational Adaptation Error



Issue: psycopg3 cannot adapt Pillow's IFDRational objects.



Solution: Normalize all EXIF values before insertion.



NUL Byte Error



Issue: PostgreSQL text fields cannot contain 0x00.



Solution: Strip NUL bytes from all strings.



Invalid Timestamp Error



Issue: Empty EXIF timestamps ("") cause PostgreSQL errors.



Solution: Convert empty strings to None.



Decompression Bomb Warning



Issue: Pillow warns or errors on large images.



Solution: Set Image.MAX\_IMAGE\_PIXELS = None.



7\. Coding Standards



General



Use psycopg3 context managers



Avoid global mutable state



Use explicit imports



Prefer pure functions for EXIF parsing



Performance



Avoid reloading CLIP model per image



Avoid unnecessary disk I/O



Use batch commits



Safety



Validate file existence before processing



Catch and log image load errors



8\. Future Extensions



This repository is designed to support future enhancements:



pHash generation



Face embeddings



Object detection



Caption generation



Parallel ingestion pipeline



Crash-safe resume markers



Deterministic directory traversal



9\. Repository Conventions



File Naming



All documentation files use the CoPilot prefix:



copilot.md



copilot\_agents.md



copilot\_done\_tasks.md



.gitignore



A modern ignore file is maintained for:



Python



Conda



DuckDB



PostgreSQL



Torch/CLIP caches



Windows 11 temp files



10\. Summary



This document captures the full technical context required to maintain and extend the ingestion pipeline. It includes environment standards, image processing rules, EXIF normalization, CLIP embedding logic, PostgreSQL integration, and lessons learned from debugging.



Future agents should refer to this file before modifying or extending the system.

