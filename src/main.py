import argparse
import logging
from pathlib import Path
from file_handler import get_video_files
from video_processor import VideoProcessor
from config import setup_logging

def parse_args():
    parser = argparse.ArgumentParser(description='Manage audio and subtitle tracks in video files.')
    parser.add_argument('input_dir', type=str, help='Directory containing video files')
    
    # Audio track selection group
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument('--remove-audio-languages', type=str, 
                            help='Comma-separated list of language codes to remove from audio (e.g., "eng,jpn")')
    audio_group.add_argument('--keep-audio-languages', type=str, 
                            help='Comma-separated list of audio language codes to keep, remove others')
    
    # Subtitle track selection group
    subtitle_group = parser.add_mutually_exclusive_group()
    subtitle_group.add_argument('--remove-subtitle-languages', type=str, 
                              help='Comma-separated list of language codes to remove from subtitles')
    subtitle_group.add_argument('--keep-subtitle-languages', type=str, 
                              help='Comma-separated list of subtitle language codes to keep, remove others')
    
    # Track type selection (now optional as languages can be specified separately)
    parser.add_argument('--audio', action='store_true', help='Process audio tracks')
    parser.add_argument('--subtitles', action='store_true', help='Process subtitle tracks')
    
    # Other options
    parser.add_argument('--recursive', action='store_true', help='Search for videos recursively')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--list-tracks', action='store_true', help='List all tracks in the video files without making changes')
    return parser.parse_args()

def parse_language_list(lang_string: str) -> list[str]:
    """Parse comma-separated language string into list."""
    return [x.strip().lower() for x in lang_string.split(',')] if lang_string else []

def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        input_path = Path(args.input_dir)
        
        # Parse language lists for audio and subtitles separately
        remove_audio_languages = parse_language_list(args.remove_audio_languages)
        keep_audio_languages = parse_language_list(args.keep_audio_languages)
        remove_subtitle_languages = parse_language_list(args.remove_subtitle_languages)
        keep_subtitle_languages = parse_language_list(args.keep_subtitle_languages)
        
        # Set process flags based on whether language options are specified
        process_audio = args.audio or bool(remove_audio_languages or keep_audio_languages)
        process_subtitles = args.subtitles or bool(remove_subtitle_languages or keep_subtitle_languages)
        
        # Ensure at least one track type will be processed
        if not (process_audio or process_subtitles):
            logger.error("Must specify at least one track type to process (use --audio, --subtitles, "
                        "or specify languages to keep/remove)")
            return 1
        
        videos = get_video_files(input_path, recursive=args.recursive)
        processor = VideoProcessor(dry_run=args.dry_run)
        
        for video_path in videos:
            try:
                if args.list_tracks:
                    processor.list_tracks(video_path)
                    continue
                    
                # Preview space savings
                processor.preview_space_savings(
                    video_path,
                    process_audio=process_audio,
                    process_subtitles=process_subtitles,
                    remove_audio_languages=remove_audio_languages,
                    keep_audio_languages=keep_audio_languages,
                    remove_subtitle_languages=remove_subtitle_languages,
                    keep_subtitle_languages=keep_subtitle_languages
                )
                
                if not args.dry_run:
                    processor.process_video(
                        video_path,
                        process_audio=process_audio,
                        process_subtitles=process_subtitles,
                        remove_audio_languages=remove_audio_languages,
                        keep_audio_languages=keep_audio_languages,
                        remove_subtitle_languages=remove_subtitle_languages,
                        keep_subtitle_languages=keep_subtitle_languages
                    )
            except Exception as e:
                logger.error(f"Error processing {video_path}: {str(e)}")
                continue
                
    except Exception as e:
        logger.error(f"Program error: {str(e)}")
        return 1
    
    return 0

if __name__ == '__main__':
    main()