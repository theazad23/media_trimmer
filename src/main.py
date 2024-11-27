import argparse
import logging
from pathlib import Path
from .file_handler import get_video_files
from .space_analyzer import format_size
from .video_processor import VideoProcessor
from .config import setup_logging

def parse_args():
    parser = argparse.ArgumentParser(description='Manage audio and subtitle tracks in video files.')
    parser.add_argument('input_dir', type=str, help='Directory containing video files')
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument('--remove-audio-languages', type=str, 
                            help='Comma-separated list of language codes to remove from audio (e.g., "eng,jpn")')
    audio_group.add_argument('--keep-audio-languages', type=str, 
                            help='Comma-separated list of audio language codes to keep, remove others')
    subtitle_group = parser.add_mutually_exclusive_group()
    subtitle_group.add_argument('--remove-subtitle-languages', type=str, 
                              help='Comma-separated list of language codes to remove from subtitles')
    subtitle_group.add_argument('--keep-subtitle-languages', type=str, 
                              help='Comma-separated list of subtitle language codes to keep, remove others')
    parser.add_argument('--audio', action='store_true', help='Process audio tracks')
    parser.add_argument('--subtitles', action='store_true', help='Process subtitle tracks')
    parser.add_argument('--recursive', action='store_true', help='Search for videos recursively')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--list-tracks', action='store_true', 
                       help='List all tracks in the video files without making changes')
    parser.add_argument('--backup', action='store_true', 
                       help='Create a .bak copy of original files before processing')
    parser.add_argument('--batch-size', type=int, default=3,
                       help='Number of videos to process simultaneously (default: 3)')
    parser.add_argument('--max-workers', type=int,
                       help='Maximum number of worker processes (default: number of CPUs - 1)')
    parser.add_argument('--limit', type=int,
                       help='Maximum number of video files to process (default: no limit)')
    return parser.parse_args()

def parse_language_list(lang_string: str) -> list[str]:
    """Parse comma-separated language string into list."""
    return [x.strip().lower() for x in lang_string.split(',')] if lang_string else []

def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        input_path = Path(args.input_dir).resolve()
        remove_audio_languages = parse_language_list(args.remove_audio_languages)
        keep_audio_languages = parse_language_list(args.keep_audio_languages)
        remove_subtitle_languages = parse_language_list(args.remove_subtitle_languages)
        keep_subtitle_languages = parse_language_list(args.keep_subtitle_languages)
        
        process_audio = args.audio or bool(remove_audio_languages or keep_audio_languages)
        process_subtitles = args.subtitles or bool(remove_subtitle_languages or keep_subtitle_languages)
        
        if not (process_audio or process_subtitles):
            logger.error("Must specify at least one track type to process (use --audio, --subtitles, "
                        "or specify languages to keep/remove)")
            return 1

        videos = get_video_files(input_path, recursive=args.recursive)
        total_videos = len(videos)
        logger.info(f"\nFound {total_videos} video{'s' if total_videos != 1 else ''}")
        
        if total_videos == 0:
            logger.warning("No video files found to process")
            return 0

        processor = VideoProcessor(
            dry_run=args.dry_run,
            backup=args.backup,
            max_workers=args.max_workers,
            batch_size=args.batch_size,
            file_limit=args.limit
        )

        if args.list_tracks:
            for video in videos:
                processor.list_tracks(video)
            return 0

        process_params = {
            'process_audio': process_audio,
            'process_subtitles': process_subtitles,
            'remove_audio_languages': remove_audio_languages,
            'keep_audio_languages': keep_audio_languages,
            'remove_subtitle_languages': remove_subtitle_languages,
            'keep_subtitle_languages': keep_subtitle_languages
        }

        results = processor.process_videos(videos, **process_params)
        
        logger.info("\nProcessing Summary")
        logger.info("=" * 80)
        logger.info(f"Total files found:      {results['total_videos']}")
        if args.limit:
            logger.info(f"Files scanned:         {results['files_scanned']}")
        logger.info(f"Files needing changes:  {results['files_needing_changes']}")
        logger.info(f"Successfully processed: {results['successful']}")
        
        if results['failed'] > 0:
            logger.error(f"Failed to process:     {results['failed']}")
            logger.error("\nErrors:")
            for error in results['errors']:
                logger.error(f"  - {error}")

        if results['total_original_size'] > 0 and results['total_savings'] > 0:
            percentage = (results['total_savings'] / results['total_original_size']) * 100
            logger.info(f"\nSpace Analysis")
            logger.info(f"Total size of files:   {format_size(results['total_original_size'])}")
            logger.info(f"Total potential saves: {format_size(results['total_savings'])} ({percentage:.1f}%)")

        if args.dry_run:
            logger.info("\nThis was a dry run - no files were modified.")
            logger.info("Run without --dry-run to apply the changes.")
            
    except Exception as e:
        logger.error(f"Program error: {str(e)}")
        return 1
        
    return 0

if __name__ == '__main__':
    main()