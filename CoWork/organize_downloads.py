# organize_downloads.py
"""
Downloads Folder Analyzer and Organizer
=======================================
A Python script that analyzes and organizes files in S:\\downloads on Windows 11.

This provides programmatic control similar to what Cowork does via its GUI.
You can also use this script's output as context for Cowork sessions.

Usage:
    python organize_downloads.py --analyze           # Analyze only (dry run)
    python organize_downloads.py --organize          # Move files into categories
    python organize_downloads.py --report            # Generate DuckDB report
    python organize_downloads.py --exif              # Extract EXIF from images
"""

import os
import sys
import json
import shutil
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Optional

# Optional imports with graceful degradation
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False
    print("Warning: DuckDB not installed. Install with: pip install duckdb")

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: Pillow not installed. Install with: pip install Pillow")


# =============================================================================
# Configuration
# =============================================================================

DOWNLOADS_PATH = Path(r"S:\downloads")

# File category mappings
CATEGORY_RULES = {
    "Documents": {
        "extensions": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", 
                       ".xlsx", ".csv", ".ppt", ".pptx", ".md", ".json", ".xml"],
        "subfolder_by": "extension"
    },
    "Images": {
        "extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", 
                       ".ico", ".tiff", ".raw", ".heic", ".avif"],
        "subfolder_by": "date"
    },
    "Videos": {
        "extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", 
                       ".m4v", ".mpeg", ".mpg"],
        "subfolder_by": "none"
    },
    "Audio": {
        "extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"],
        "subfolder_by": "none"
    },
    "Archives": {
        "extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
        "subfolder_by": "none"
    },
    "Installers": {
        "extensions": [".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"],
        "subfolder_by": "none"
    },
    "Code": {
        "extensions": [".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", 
                       ".c", ".h", ".go", ".rs", ".sql", ".sh", ".bat", ".ps1"],
        "subfolder_by": "extension"
    },
    "Data": {
        "extensions": [".parquet", ".arrow", ".feather", ".db", ".sqlite", 
                       ".duckdb", ".npy", ".npz", ".pkl", ".pickle"],
        "subfolder_by": "none"
    },
}


@dataclass
class FileInfo:
    """Information about a single file."""
    path: str
    name: str
    extension: str
    size_bytes: int
    size_human: str
    created: datetime
    modified: datetime
    category: str
    md5_hash: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None


# =============================================================================
# Core Functions
# =============================================================================

def get_file_hash(filepath: Path, chunk_size: int = 8192) -> str:
    """Calculate MD5 hash of a file."""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def categorize_file(extension: str) -> str:
    """Determine category based on file extension."""
    ext_lower = extension.lower()
    for category, rules in CATEGORY_RULES.items():
        if ext_lower in rules["extensions"]:
            return category
    return "Other"


def scan_directory(path: Path, compute_hashes: bool = False) -> list[FileInfo]:
    """Scan directory and collect file information."""
    files = []
    hash_map = {}  # For duplicate detection
    
    for item in path.rglob("*"):
        if item.is_file():
            try:
                stat = item.stat()
                ext = item.suffix.lower()
                
                file_info = FileInfo(
                    path=str(item),
                    name=item.name,
                    extension=ext,
                    size_bytes=stat.st_size,
                    size_human=human_readable_size(stat.st_size),
                    created=datetime.fromtimestamp(stat.st_ctime),
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    category=categorize_file(ext),
                )
                
                if compute_hashes and stat.st_size < 100_000_000:  # Skip files > 100MB
                    file_hash = get_file_hash(item)
                    file_info.md5_hash = file_hash
                    
                    if file_hash in hash_map:
                        file_info.is_duplicate = True
                        file_info.duplicate_of = hash_map[file_hash]
                    else:
                        hash_map[file_hash] = str(item)
                
                files.append(file_info)
                
            except (PermissionError, OSError) as e:
                print(f"  Skipping {item}: {e}")
    
    return files


def analyze_files(files: list[FileInfo]) -> dict:
    """Generate analysis summary."""
    summary = {
        "total_files": len(files),
        "total_size_bytes": sum(f.size_bytes for f in files),
        "by_category": defaultdict(lambda: {"count": 0, "size_bytes": 0}),
        "by_extension": defaultdict(lambda: {"count": 0, "size_bytes": 0}),
        "duplicates": [],
        "largest_files": [],
        "oldest_files": [],
        "newest_files": [],
    }
    
    for f in files:
        summary["by_category"][f.category]["count"] += 1
        summary["by_category"][f.category]["size_bytes"] += f.size_bytes
        
        summary["by_extension"][f.extension]["count"] += 1
        summary["by_extension"][f.extension]["size_bytes"] += f.size_bytes
        
        if f.is_duplicate:
            summary["duplicates"].append(asdict(f))
    
    # Top 10 largest files
    sorted_by_size = sorted(files, key=lambda x: x.size_bytes, reverse=True)
    summary["largest_files"] = [asdict(f) for f in sorted_by_size[:10]]
    
    # 10 oldest files
    sorted_by_date = sorted(files, key=lambda x: x.modified)
    summary["oldest_files"] = [asdict(f) for f in sorted_by_date[:10]]
    
    # 10 newest files
    summary["newest_files"] = [asdict(f) for f in sorted_by_date[-10:]]
    
    # Convert defaultdicts to regular dicts for JSON serialization
    summary["by_category"] = dict(summary["by_category"])
    summary["by_extension"] = dict(summary["by_extension"])
    summary["total_size_human"] = human_readable_size(summary["total_size_bytes"])
    
    return summary


def organize_files(files: list[FileInfo], base_path: Path, dry_run: bool = True) -> list[dict]:
    """Organize files into category folders."""
    operations = []
    
    for f in files:
        if f.category == "Other":
            continue
            
        source = Path(f.path)
        
        # Skip if already in a category folder
        if f.category in str(source.parent):
            continue
        
        # Determine destination
        dest_folder = base_path / f.category
        rules = CATEGORY_RULES.get(f.category, {})
        
        if rules.get("subfolder_by") == "extension":
            dest_folder = dest_folder / f.extension.lstrip(".").upper()
        elif rules.get("subfolder_by") == "date":
            dest_folder = dest_folder / f.modified.strftime("%Y-%m")
        
        dest_path = dest_folder / f.name
        
        # Handle name conflicts
        counter = 1
        while dest_path.exists():
            stem = source.stem
            dest_path = dest_folder / f"{stem}_{counter}{f.extension}"
            counter += 1
        
        operation = {
            "source": str(source),
            "destination": str(dest_path),
            "category": f.category,
        }
        operations.append(operation)
        
        if not dry_run:
            dest_folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest_path))
            print(f"  Moved: {source.name} -> {dest_path}")
    
    return operations


def extract_exif(files: list[FileInfo]) -> list[dict]:
    """Extract EXIF metadata from image files."""
    if not HAS_PIL:
        print("Pillow required for EXIF extraction")
        return []
    
    exif_data = []
    image_extensions = {".jpg", ".jpeg", ".tiff", ".png", ".heic"}
    
    for f in files:
        if f.extension.lower() not in image_extensions:
            continue
            
        try:
            with Image.open(f.path) as img:
                raw_exif = img._getexif()
                if raw_exif:
                    decoded = {TAGS.get(k, k): v for k, v in raw_exif.items()}
                    exif_data.append({
                        "file_path": f.path,
                        "file_name": f.name,
                        **{k: str(v) for k, v in decoded.items() 
                           if isinstance(v, (str, int, float))}
                    })
        except Exception as e:
            print(f"  EXIF extraction failed for {f.name}: {e}")
    
    return exif_data


def create_duckdb_report(files: list[FileInfo], output_path: Path):
    """Create a DuckDB database with file analysis."""
    if not HAS_DUCKDB:
        print("DuckDB required for database report")
        return
    
    db_path = output_path / "downloads_analysis.duckdb"
    
    with duckdb.connect(str(db_path)) as con:
        # Create files table
        con.execute("""
            CREATE OR REPLACE TABLE files (
                path VARCHAR,
                name VARCHAR,
                extension VARCHAR,
                size_bytes BIGINT,
                created TIMESTAMP,
                modified TIMESTAMP,
                category VARCHAR,
                md5_hash VARCHAR,
                is_duplicate BOOLEAN
            )
        """)
        
        # Insert data
        for f in files:
            con.execute("""
                INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                f.path, f.name, f.extension, f.size_bytes,
                f.created, f.modified, f.category, f.md5_hash, f.is_duplicate
            ])
        
        # Create summary views
        con.execute("""
            CREATE OR REPLACE VIEW category_summary AS
            SELECT 
                category,
                COUNT(*) as file_count,
                SUM(size_bytes) as total_bytes,
                ROUND(SUM(size_bytes) / 1024.0 / 1024.0, 2) as total_mb
            FROM files
            GROUP BY category
            ORDER BY total_bytes DESC
        """)
        
        con.execute("""
            CREATE OR REPLACE VIEW extension_summary AS
            SELECT 
                extension,
                COUNT(*) as file_count,
                SUM(size_bytes) as total_bytes,
                ROUND(SUM(size_bytes) / 1024.0 / 1024.0, 2) as total_mb
            FROM files
            GROUP BY extension
            ORDER BY total_bytes DESC
        """)
        
        con.execute("""
            CREATE OR REPLACE VIEW duplicates AS
            SELECT * FROM files WHERE is_duplicate = true
        """)
        
        print(f"\n  DuckDB database created: {db_path}")
        print("\n  Available tables/views:")
        print("    - files: All file metadata")
        print("    - category_summary: Size by category")
        print("    - extension_summary: Size by extension")
        print("    - duplicates: Duplicate files")
        
        # Quick summary
        result = con.execute("SELECT * FROM category_summary").fetchall()
        print("\n  Category Summary:")
        for row in result:
            print(f"    {row[0]}: {row[1]} files, {row[3]} MB")


def generate_cowork_prompt(summary: dict) -> str:
    """Generate a prompt you can use with Cowork for further organization."""
    prompt = f"""I've analyzed my downloads folder (S:\\downloads) and found:

- {summary['total_files']} total files
- {summary['total_size_human']} total size

Category breakdown:
"""
    for cat, data in sorted(summary["by_category"].items(), 
                            key=lambda x: x[1]["size_bytes"], reverse=True):
        prompt += f"- {cat}: {data['count']} files ({human_readable_size(data['size_bytes'])})\n"
    
    if summary["duplicates"]:
        prompt += f"\nFound {len(summary['duplicates'])} duplicate files that could be removed.\n"
    
    prompt += """
Please help me:
1. Review the largest files and suggest which to delete
2. Identify old files (>1 year) that might be obsolete
3. Suggest a better organization structure
4. Clean up duplicate files safely
"""
    return prompt


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Analyze and organize downloads folder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python organize_downloads.py --analyze
  python organize_downloads.py --analyze --hashes
  python organize_downloads.py --organize --dry-run
  python organize_downloads.py --organize
  python organize_downloads.py --report
  python organize_downloads.py --exif
  python organize_downloads.py --cowork-prompt
        """
    )
    
    parser.add_argument("--path", type=Path, default=DOWNLOADS_PATH,
                        help="Path to analyze (default: S:\\downloads)")
    parser.add_argument("--analyze", action="store_true",
                        help="Analyze files and show summary")
    parser.add_argument("--hashes", action="store_true",
                        help="Compute MD5 hashes for duplicate detection")
    parser.add_argument("--organize", action="store_true",
                        help="Organize files into category folders")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be moved without moving")
    parser.add_argument("--report", action="store_true",
                        help="Generate DuckDB report")
    parser.add_argument("--exif", action="store_true",
                        help="Extract EXIF from images")
    parser.add_argument("--cowork-prompt", action="store_true",
                        help="Generate a prompt for Cowork")
    parser.add_argument("--output", type=Path, default=Path("."),
                        help="Output directory for reports")
    
    args = parser.parse_args()
    
    if not any([args.analyze, args.organize, args.report, args.exif, args.cowork_prompt]):
        args.analyze = True  # Default action
    
    if not args.path.exists():
        print(f"Error: Path does not exist: {args.path}")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"Downloads Folder Analyzer")
    print(f"{'='*60}")
    print(f"Scanning: {args.path}")
    
    # Scan files
    print("\nScanning files...")
    files = scan_directory(args.path, compute_hashes=args.hashes)
    print(f"  Found {len(files)} files")
    
    # Generate analysis
    summary = analyze_files(files)
    
    if args.analyze:
        print(f"\n{'='*60}")
        print("ANALYSIS SUMMARY")
        print(f"{'='*60}")
        print(f"\nTotal: {summary['total_files']} files, {summary['total_size_human']}")
        
        print("\nBy Category:")
        for cat, data in sorted(summary["by_category"].items(), 
                                key=lambda x: x[1]["size_bytes"], reverse=True):
            print(f"  {cat:12} {data['count']:5} files  {human_readable_size(data['size_bytes']):>10}")
        
        print("\nTop 5 Extensions:")
        sorted_ext = sorted(summary["by_extension"].items(), 
                           key=lambda x: x[1]["size_bytes"], reverse=True)[:5]
        for ext, data in sorted_ext:
            print(f"  {ext:12} {data['count']:5} files  {human_readable_size(data['size_bytes']):>10}")
        
        if summary["duplicates"]:
            print(f"\nDuplicates Found: {len(summary['duplicates'])} files")
        
        print("\nLargest Files:")
        for f in summary["largest_files"][:5]:
            print(f"  {f['size_human']:>10}  {f['name'][:50]}")
        
        # Save JSON report
        report_path = args.output / "downloads_analysis.json"
        with open(report_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nJSON report saved: {report_path}")
    
    if args.organize:
        print(f"\n{'='*60}")
        print("ORGANIZING FILES" + (" (DRY RUN)" if args.dry_run else ""))
        print(f"{'='*60}")
        
        operations = organize_files(files, args.path, dry_run=args.dry_run)
        print(f"\n  {len(operations)} files would be moved")
        
        if args.dry_run and operations:
            print("\n  Sample operations:")
            for op in operations[:10]:
                print(f"    {Path(op['source']).name} -> {op['category']}/")
    
    if args.report:
        print(f"\n{'='*60}")
        print("CREATING DUCKDB REPORT")
        print(f"{'='*60}")
        create_duckdb_report(files, args.output)
    
    if args.exif:
        print(f"\n{'='*60}")
        print("EXTRACTING EXIF DATA")
        print(f"{'='*60}")
        exif_data = extract_exif(files)
        if exif_data:
            exif_path = args.output / "exif_metadata.json"
            with open(exif_path, "w") as f:
                json.dump(exif_data, f, indent=2)
            print(f"  Extracted EXIF from {len(exif_data)} images")
            print(f"  Saved to: {exif_path}")
    
    if args.cowork_prompt:
        print(f"\n{'='*60}")
        print("COWORK PROMPT")
        print(f"{'='*60}")
        prompt = generate_cowork_prompt(summary)
        print(prompt)
        
        prompt_path = args.output / "cowork_prompt.txt"
        with open(prompt_path, "w") as f:
            f.write(prompt)
        print(f"\nSaved to: {prompt_path}")


if __name__ == "__main__":
    main()
