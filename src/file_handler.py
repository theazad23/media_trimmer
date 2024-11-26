from pathlib import Path
import logging

logger = logging.getLogger(__name__)

VALID_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv'}

def get_video_files(directory: Path, recursive: bool = False) -> list[Path]:
    """Get all video files in the specified directory."""
    if not directory.is_dir():
        raise ValueError(f"'{directory}' is not a valid directory")
    
    pattern = '**/*' if recursive else '*'
    video_files = []
    
    for file_path in directory.glob(pattern):
        if file_path.suffix.lower() in VALID_EXTENSIONS:
            video_files.append(file_path)
            logger.info(f"Found video file: {file_path}")
    
    return video_files