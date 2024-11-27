import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

VALID_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv'}

def get_video_files(directory: Path, recursive: bool = False) -> list[Path]:
    """Get all video files in the specified directory."""
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError(f"'{directory}' is not a valid directory")
    if not os.access(directory, os.R_OK):
        raise ValueError(f"'{directory}' is not readable")

    pattern = '**/*' if recursive else '*'
    video_files = []
    
    for file_path in directory.glob(pattern):
        try:
            if (file_path.suffix.lower() in VALID_EXTENSIONS and 
                '.processing.' not in file_path.name):  # Skip processing files
                resolved_path = file_path.resolve()
                if resolved_path.exists() and os.access(resolved_path, os.R_OK):
                    video_files.append(resolved_path)
                    logger.info(f"Found video file: {resolved_path}")
                else:
                    logger.warning(f"File exists but is not accessible: {resolved_path}")
        except Exception as e:
            logger.warning(f"Error processing path {file_path}: {str(e)}")
            
    return video_files