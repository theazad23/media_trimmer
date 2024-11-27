import re
import select
import subprocess
import logging
import multiprocessing
from pathlib import Path
import json
import shutil
import sys
import time
from typing import List, Dict, Any, Optional
from tqdm import tqdm
from .track_manager import TrackInfo, TrackManager
from .space_analyzer import SpaceAnalyzer, format_size

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, dry_run: bool = False, backup: bool = False, 
                 max_workers: int = None, batch_size: int = 3,
                 file_limit: int = None):
        self.dry_run = dry_run
        self.backup = backup
        self.max_workers = max_workers or max(1, multiprocessing.cpu_count() - 1)
        self.batch_size = batch_size
        self.file_limit = file_limit
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            subprocess.run(['ffprobe', '-version'], capture_output=True, check=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("ffmpeg and/or ffprobe is not installed or not accessible")
        except FileNotFoundError:
            raise RuntimeError("ffmpeg and/or ffprobe is not installed")

    def _parse_progress(self, line: str) -> Optional[float]:
        """Parse progress info from ffmpeg output."""
        try:
            if "time=" in line:
                time_str = line.split("time=")[1].split()[0]
                if ':' in time_str:
                    h, m, s = map(float, time_str.replace(',', '.').split(':'))
                    return h * 3600 + m * 60 + s
                return float(time_str)
            return None
        except (ValueError, IndexError):
            return None

    def _get_video_duration(self, video_path: Path) -> float:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path)
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            return 0

    def get_tracks(self, video_path: Path) -> List[TrackInfo]:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-print_format', 'json',
            '-show_streams',
            str(video_path)
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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
            raise RuntimeError(f"Failed to analyze video file: {error_msg}")
        except json.JSONDecodeError:
            raise RuntimeError("Failed to parse ffprobe output")
        except Exception as e:
            raise RuntimeError(f"Unexpected error analyzing video: {str(e)}")

    def list_tracks(self, video_path: Path):
        logger.info(f"Analyzing: {video_path.name}", extra={'subseparator': True})
        tracks = self.get_tracks(video_path)
        if not tracks:
            logger.warning("No audio or subtitle tracks found in the video")
            return
        manager = TrackManager(tracks)
        logger.info(manager.get_track_summary())

    def preview_space_savings(self, video_path: Path, **kwargs):
        analyzer = SpaceAnalyzer()
        savings = analyzer.analyze_savings(video_path, **kwargs)
        original_size = format_size(savings['original_size'])
        total_savings = format_size(savings['total_savings'])
        percentage = (savings['total_savings'] / savings['original_size'] * 100) if savings['original_size'] > 0 else 0
        
        logger.info(f"Track Analysis for: {video_path.name}")
        logger.info(f"Original Size: {original_size}")
        logger.info(f"Potential Savings: {total_savings} ({percentage:.1f}%)")
        return savings

    def _build_ffmpeg_command(self, video_path: Path, mapping: List[str], temp_path: Path) -> List[str]:
        return [
            'ffmpeg',
            '-i', str(video_path),
            '-loglevel', 'info',
            '-stats',
            *mapping,
            '-c', 'copy',
            str(temp_path)
        ]


    def process_videos(self, videos: List[Path], **kwargs) -> Dict[str, Any]:
        total_videos = len(videos)
        files_scanned = 0
        successful_count = 0
        failed_count = 0
        errors = []
        videos_to_process = []
        files_needing_changes = 0
        total_savings = 0
        total_original_size = 0

        logger.info(f"\nFound {total_videos} videos")
        if self.file_limit:
            logger.info(f"Processing limit: {self.file_limit} files")

        # Clean up any existing .processing files
        for video in videos:
            processing_path = video.with_name(f"{video.stem}.processing{video.suffix}")
            if processing_path.exists():
                try:
                    processing_path.unlink()
                    logger.info(f"Cleaned up existing processing file: {processing_path.name}")
                except Exception as e:
                    logger.error(f"Failed to clean up processing file {processing_path.name}: {str(e)}")
                    return {
                        'total_videos': total_videos,
                        'files_scanned': 0,
                        'files_needing_changes': 0,
                        'successful': 0,
                        'failed': 1,
                        'total_savings': 0,
                        'total_original_size': 0,
                        'errors': [f"Failed to clean up existing processing files: {str(e)}"]
                    }

        logger.info("\nAnalyzing videos...")
        for video_path in tqdm(videos, desc="Analyzing", unit="file"):
            files_scanned += 1
            if self.file_limit and len(videos_to_process) >= self.file_limit:
                break

            try:
                tracks = self.get_tracks(video_path)
                manager = TrackManager(tracks)
                tracks_to_remove = []

                if kwargs.get('process_audio'):
                    audio_to_remove = manager.filter_tracks_by_type(
                        'audio',
                        kwargs.get('remove_audio_languages'),
                        kwargs.get('keep_audio_languages')
                    )
                    tracks_to_remove.extend(audio_to_remove)

                if kwargs.get('process_subtitles'):
                    subs_to_remove = manager.filter_tracks_by_type(
                        'subtitle',
                        kwargs.get('remove_subtitle_languages'),
                        kwargs.get('keep_subtitle_languages')
                    )
                    tracks_to_remove.extend(subs_to_remove)

                if tracks_to_remove:
                    videos_to_process.append((video_path, tracks_to_remove))
                    files_needing_changes += 1
                    savings = self.preview_space_savings(video_path, **kwargs)
                    total_original_size += savings['original_size']
                    total_savings += savings['total_savings']

            except Exception as e:
                logger.warning(f"Error analyzing {video_path.name}: {str(e)}")

        if not videos_to_process:
            return {
                'total_videos': total_videos,
                'files_scanned': files_scanned,
                'files_needing_changes': 0,
                'successful': 0,
                'failed': 0,
                'total_savings': 0,
                'total_original_size': 0,
                'errors': []
            }

        logger.info(f"\nFound {files_needing_changes} files that need processing")
        if self.file_limit:
            logger.info(f"Will process maximum {self.file_limit} files")
        if total_savings > 0:
            percentage = (total_savings / total_original_size) * 100
            logger.info(f"Potential space savings: {format_size(total_savings)} ({percentage:.1f}%)")

        logger.info("\nStarting processing...")
        with tqdm(total=len(videos_to_process), desc="Overall Progress", unit="file") as overall_pbar:
            for i in range(0, len(videos_to_process), self.batch_size):
                batch = videos_to_process[i:i + self.batch_size]
                active_processes = {}
                progress_bars = {}

                for video_path, tracks_to_remove in batch:
                    try:
                        duration = self._get_video_duration(video_path)
                        if not duration:
                            raise ValueError(f"Could not determine duration for {video_path.name}")

                        pbar = tqdm(
                            total=100,
                            desc=f"Processing {video_path.name[:50]}...",
                            unit="%",
                            position=len(progress_bars) + 1,
                            leave=False
                        )
                        progress_bars[video_path] = pbar

                        temp_path = video_path.with_name(f"{video_path.stem}.processing{video_path.suffix}")
                        mapping = ['-map', '0']
                        for idx in tracks_to_remove:
                            mapping.extend(['-map', f'-0:{idx}'])

                        cmd = [
                            'ffmpeg',
                            '-i', str(video_path),
                            '-stats',
                            '-loglevel', 'info',
                            *mapping,
                            '-c', 'copy',
                            str(temp_path)
                        ]
                        
                        process = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            universal_newlines=True,
                            bufsize=1
                        )
                        active_processes[video_path] = (process, duration, temp_path)

                    except Exception as e:
                        logger.error(f"Failed to start {video_path.name}: {str(e)}")
                        errors.append(f"{video_path.name}: {str(e)}")
                        failed_count += 1

                while active_processes:
                    for video_path, (process, duration, temp_path) in list(active_processes.items()):
                        pbar = progress_bars[video_path]

                        if process.poll() is not None:
                            if process.returncode == 0:
                                try:
                                    if self.backup:
                                        backup_path = video_path.with_suffix(video_path.suffix + '.bak')
                                        shutil.copy2(video_path, backup_path)
                                    shutil.move(str(temp_path), str(video_path))
                                    successful_count += 1
                                    pbar.n = 100
                                    pbar.refresh()
                                    logger.info(f"✓ Completed: {video_path.name}")
                                except Exception as e:
                                    failed_count += 1
                                    errors.append(f"{video_path.name}: Failed to move file: {str(e)}")
                                    logger.error(f"✗ Failed: {video_path.name}")
                            else:
                                failed_count += 1
                                error_output = process.stderr.read()
                                errors.append(f"{video_path.name}: {error_output}")
                                logger.error(f"✗ Failed: {video_path.name}")
                                if temp_path.exists():
                                    temp_path.unlink()

                            pbar.close()
                            overall_pbar.update(1)
                            del active_processes[video_path]
                            continue

                        stderr_ready = select.select([process.stderr], [], [], 0.1)[0]
                        if stderr_ready:
                            line = process.stderr.readline().strip()
                            if line:
                                time_match = re.search(r'time=(\d+:\d+:\d+\.\d+)', line)
                                if time_match:
                                    time_str = time_match.group(1)
                                    h, m, s = map(float, time_str.split(':'))
                                    progress = h * 3600 + m * 60 + s
                                    percent = min(100, (progress / duration) * 100)
                                    pbar.n = percent
                                    pbar.refresh()

                    time.sleep(0.1)

        return {
            'total_videos': total_videos,
            'files_scanned': files_scanned,
            'files_needing_changes': files_needing_changes,
            'successful': successful_count,
            'failed': failed_count,
            'total_savings': total_savings,
            'total_original_size': total_original_size,
            'errors': errors
        }