import subprocess
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import json
import tempfile
import shutil
import time
from typing import List, Dict, Any
from .track_manager import TrackInfo, TrackManager
from .space_analyzer import SpaceAnalyzer, format_size

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, dry_run: bool = False, backup: bool = False, 
                 max_workers: int = None, batch_size: int = 3):
        self.dry_run = dry_run
        self.backup = backup
        self.max_workers = max_workers or max(1, multiprocessing.cpu_count() - 1)
        self.batch_size = batch_size
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """Verify ffmpeg is installed and accessible."""
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            subprocess.run(['ffprobe', '-version'], capture_output=True, check=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("ffmpeg and/or ffprobe is not installed or not accessible")
        except FileNotFoundError:
            raise RuntimeError("ffmpeg and/or ffprobe is not installed")

    def get_tracks(self, video_path: Path) -> List[TrackInfo]:
        """Get information about all tracks in the video."""
        cmd = [
            'ffprobe',
            '-v', 'error',  # Only show errors
            '-print_format', 'json',
            '-show_streams',
            str(video_path)
        ]
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            if not data.get('streams'):
                raise RuntimeError("No streams found in the video file")
            
            tracks = []
            for i, stream in enumerate(data.get('streams', [])):
                if stream['codec_type'] not in ('audio', 'subtitle'):
                    continue
                track = TrackInfo(
                    index=i,
                    type=stream['codec_type'],
                    language=stream.get('tags', {}).get('language'),
                    title=stream.get('tags', {}).get('title'),
                    default=stream.get('disposition', {}).get('default', 0) == 1,
                    forced=stream.get('disposition', {}).get('forced', 0) == 1
                )
                tracks.append(track)
            return tracks
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "Unknown error occurred"
            logger.error(f"ffprobe error: {error_msg}")
            raise RuntimeError(f"Failed to analyze video file: {error_msg}")
        except json.JSONDecodeError:
            raise RuntimeError("Failed to parse ffprobe output")
        except Exception as e:
            raise RuntimeError(f"Unexpected error analyzing video: {str(e)}")

    def list_tracks(self, video_path: Path):
        """Display information about all tracks in the video."""
        logger.info(f"Analyzing: {video_path.name}", extra={'subseparator': True})
        tracks = self.get_tracks(video_path)
        if not tracks:
            logger.warning("No audio or subtitle tracks found in the video")
            return
        manager = TrackManager(tracks)
        logger.info(manager.get_track_summary())

    def preview_space_savings(self, video_path: Path, **kwargs):
        """Preview potential space savings from removing tracks."""
        video_path = Path(video_path).resolve()
        analyzer = SpaceAnalyzer()
        savings = analyzer.analyze_savings(video_path, **kwargs)
        tracks = self.get_tracks(video_path)
        manager = TrackManager(tracks)
        tracks_to_remove = []
        
        if kwargs.get('process_audio'):
            audio_to_remove = manager.filter_tracks_by_type('audio', 
                                                        kwargs.get('remove_audio_languages'), 
                                                        kwargs.get('keep_audio_languages'))
            tracks_to_remove.extend(audio_to_remove)
            
        if kwargs.get('process_subtitles'):
            subs_to_remove = manager.filter_tracks_by_type('subtitle', 
                                                        kwargs.get('remove_subtitle_languages'), 
                                                        kwargs.get('keep_subtitle_languages'))
            tracks_to_remove.extend(subs_to_remove)
            
        original_size = format_size(savings['original_size'])
        total_savings = format_size(savings['total_savings'])
        percentage = (savings['total_savings'] / savings['original_size'] * 100) if savings['original_size'] > 0 else 0
        
        logger.info(f"Track Analysis for: {video_path.name}")
        logger.info(f"Original Size: {original_size}")
        logger.info(f"Potential Savings: {total_savings} ({percentage:.1f}%)")
        
        return savings

    def process_video(self, video_path: Path, process_audio: bool = True,
                     process_subtitles: bool = True, remove_audio_languages: List[str] = None,
                     keep_audio_languages: List[str] = None, remove_subtitle_languages: List[str] = None,
                     keep_subtitle_languages: List[str] = None):
        """Process a video file to manage audio and subtitle tracks based on language."""
        video_path = Path(video_path).resolve()
        logger.info(f"Processing: {video_path.name}")
        
        original_size = video_path.stat().st_size
        logger.info(f"Original file size: {format_size(original_size)}")
        
        tracks = self.get_tracks(video_path)
        manager = TrackManager(tracks)
        tracks_to_remove = []
        
        if process_audio:
            audio_to_remove = manager.filter_tracks_by_type('audio', 
                                                        remove_audio_languages, 
                                                        keep_audio_languages)
            tracks_to_remove.extend(audio_to_remove)
            
        if process_subtitles:
            subs_to_remove = manager.filter_tracks_by_type('subtitle', 
                                                        remove_subtitle_languages, 
                                                        keep_subtitle_languages)
            tracks_to_remove.extend(subs_to_remove)
            
        if not tracks_to_remove:
            logger.info("No tracks to remove based on specified criteria")
            return
            
        if self.dry_run:
            logger.info(f"Would remove {len(tracks_to_remove)} tracks from {video_path.name}")
            return
            
        mapping = ['-map', '0']  # Start with all streams
        for idx in tracks_to_remove:
            mapping.extend(['-map', f'-0:{idx}'])
            
        temp_path = video_path.with_name(f"{video_path.stem}.processing{video_path.suffix}")
        logger.info(f"Temporary file location: {temp_path}")
        
        if temp_path.exists():
            temp_path.unlink()
            
        logger.info("Starting ffmpeg processing...")
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-loglevel', 'warning',    # Show warnings and errors
            '-stats',                  # Show progress stats
            *mapping,
            '-c', 'copy',
            str(temp_path)
        ]
        
        try:
            # Test write permissions
            try:
                with open(temp_path, 'wb') as f:
                    pass
                temp_path.unlink()  # Remove the test file
            except IOError as e:
                raise RuntimeError(f"Cannot write to output location: {e}")
                
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1  # Line buffered
            )
            
            error_output = []
            while True:
                stderr_line = process.stderr.readline()
                if not stderr_line and process.poll() is not None:
                    break
                if stderr_line:
                    stderr_line = stderr_line.strip()
                    if 'error' in stderr_line.lower() or 'permission denied' in stderr_line.lower():
                        error_output.append(stderr_line)
                    if 'frame=' in stderr_line or ('video:' in stderr_line and 'audio:' in stderr_line):
                        logger.info(f"Progress: {stderr_line}")
                        
            if process.returncode != 0:
                error_msg = '\n'.join(error_output) if error_output else process.stderr.read()
                raise subprocess.CalledProcessError(
                    process.returncode, 
                    cmd, 
                    output=process.stdout.read() if process.stdout else None,
                    stderr=error_msg
                )
                
            if self.backup:
                logger.info("Creating backup...")
                backup_path = video_path.with_suffix(video_path.suffix + '.bak')
                try:
                    shutil.copy2(video_path, backup_path)
                    logger.info(f"Backup created at: {backup_path.name}")
                except IOError as e:
                    raise RuntimeError(f"Failed to create backup: {e}")
                    
            logger.info("Moving processed file to final location...")
            try:
                shutil.move(str(temp_path), str(video_path))
                logger.info(f"Successfully processed: {video_path.name}")
            except IOError as e:
                raise RuntimeError(f"Failed to move processed file: {e}")
                
            logger.info("\nFinal track listing:")
            self.list_tracks(video_path)
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else "No error details available"
            logger.error(f"FFmpeg error: {error_msg}")
            if temp_path.exists():
                temp_path.unlink()
            raise
        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            if temp_path.exists():
                temp_path.unlink()
            raise
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary file {temp_path}: {e}")

    @staticmethod
    def _process_single_video(args: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single video file (static method for multiprocessing)."""
        video_path = args['video_path']
        processor = VideoProcessor(dry_run=args['dry_run'], backup=args['backup'])
        try:
            savings = processor.preview_space_savings(video_path, **args['process_params'])
            if not args['dry_run']:
                processor.process_video(video_path, **args['process_params'])
            return {
                'path': video_path,
                'success': True,
                'savings': savings,
                'error': None
            }
        except Exception as e:
            return {
                'path': video_path,
                'success': False,
                'savings': None,
                'error': str(e)
            }

    def process_videos(self, videos: List[Path], **kwargs) -> Dict[str, Any]:
        """Process videos in parallel, but in controlled batch sizes."""
        total_videos = len(videos)
        logger.info(f"\nProcessing {total_videos} videos in batches of {self.batch_size}")
        logger.info(f"Using {self.max_workers} worker processes")
        
        # Initialize counters and accumulators
        successful_count = 0
        failed_count = 0
        total_savings = 0
        total_original_size = 0
        errors = []
        
        # Process videos in batches
        for batch_start in range(0, total_videos, self.batch_size):
            batch_end = min(batch_start + self.batch_size, total_videos)
            batch_videos = videos[batch_start:batch_end]
            
            logger.info(f"\nProcessing batch {(batch_start // self.batch_size) + 1} "
                       f"({batch_start + 1}-{batch_end} of {total_videos})")
            
            # Prepare arguments for each video in the batch
            process_args = []
            for video_path in batch_videos:
                args = {
                    'video_path': video_path,
                    'dry_run': self.dry_run,
                    'backup': self.backup,
                    'process_params': kwargs
                }
                process_args.append(args)
            
            # Process the batch in parallel
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_video = {
                    executor.submit(self._process_single_video, args): args['video_path']
                    for args in process_args
                }
                
                for future in as_completed(future_to_video):
                    video_path = future_to_video[future]
                    try:
                        result = future.result()
                        if result['success']:
                            successful_count += 1
                            if result['savings']:
                                total_savings += result['savings']['total_savings']
                                total_original_size += result['savings']['original_size']
                            logger.info(f"Completed: {video_path.name}")
                        else:
                            failed_count += 1
                            errors.append(f"{video_path.name}: {result['error']}")
                            logger.error(f"Failed: {video_path.name} - {result['error']}")
                    except Exception as e:
                        failed_count += 1
                        errors.append(f"{video_path.name}: {str(e)}")
                        logger.error(f"Failed: {video_path.name} - {str(e)}")
            
            # Log batch completion
            logger.info(f"Batch {(batch_start // self.batch_size) + 1} complete")

        return {
            'total_videos': total_videos,
            'successful': successful_count,
            'failed': failed_count,
            'total_savings': total_savings,
            'total_original_size': total_original_size,
            'errors': errors
        }