# Analyze your downloads
python organize_downloads.py --analyze --hashes

# See what would be organized (dry run)
python organize_downloads.py --organize --dry-run

# 
python organize_downloads.py --exif

# Actually organize files
python organize_downloads.py --organize

# Create DuckDB report for further analysis
python organize_downloads.py --report

# Generate prompt to use in Cowork for AI-assisted cleanup
python organize_downloads.py --cowork-prompt