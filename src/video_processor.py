import subprocess
import logging
from pathlib import Path
import json
import tempfile
import shutil
from typing import List
from track_manager import TrackInfo, TrackManager
from space_analyzer import SpaceAnalyzer, format_size

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """Verify ffmpeg is installed and accessible."""
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("ffmpeg is not installed or not accessible")
    
    def get_tracks(self, video_path: Path) -> List[TrackInfo]:
        """Get information about all tracks in the video."""
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get track info: {result.stderr}")
        
        data = json.loads(result.stdout)
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
    
    def list_tracks(self, video_path: Path):
        """Display information about all tracks in the video."""
        tracks = self.get_tracks(video_path)
        manager = TrackManager(tracks)
        logger.info(f"\nTracks in {video_path}:\n{manager.get_track_summary()}")
    
    def preview_space_savings(self, video_path: Path, process_audio: bool = True,
                            process_subtitles: bool = True, remove_audio_languages: List[str] = None,
                            keep_audio_languages: List[str] = None, remove_subtitle_languages: List[str] = None,
                            keep_subtitle_languages: List[str] = None):
        """Preview potential space savings from removing tracks."""
        analyzer = SpaceAnalyzer()
        savings = analyzer.analyze_savings(
            video_path,
            process_audio=process_audio,
            process_subtitles=process_subtitles,
            remove_audio_languages=remove_audio_languages,
            keep_audio_languages=keep_audio_languages,
            remove_subtitle_languages=remove_subtitle_languages,
            keep_subtitle_languages=keep_subtitle_languages
        )
        
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
        
        original_size = format_size(savings['original_size'])
        total_savings = format_size(savings['total_savings'])
        percentage = (savings['total_savings'] / savings['original_size']) * 100
        
        logger.info(f"\nSpace Analysis for {video_path.name}:")
        logger.info(f"Original Size: {original_size}")
        logger.info(f"Potential Savings: {total_savings} ({percentage:.1f}%)")
        
        # Group tracks by type for reporting
        audio_tracks_remove = [t for t in tracks if t.type == 'audio' and t.index in tracks_to_remove]
        subtitle_tracks_remove = [t for t in tracks if t.type == 'subtitle' and t.index in tracks_to_remove]
        
        breakdown = savings['breakdown']
        if breakdown['audio']['tracks'] > 0:
            audio_savings = format_size(breakdown['audio']['bytes'])
            languages = [f"{t.language or 'Unknown'}" + (f" ({t.title})" if t.title else "") 
                        for t in audio_tracks_remove]
            logger.info(f"Audio Tracks to Remove: {breakdown['audio']['tracks']} ({audio_savings})")
            logger.info(f"  Languages: {', '.join(languages)}")
        
        if breakdown['subtitle']['tracks'] > 0:
            subtitle_savings = format_size(breakdown['subtitle']['bytes'])
            languages = [f"{t.language or 'Unknown'}" + (f" ({t.title})" if t.title else "") 
                        for t in subtitle_tracks_remove]
            logger.info(f"Subtitle Tracks to Remove: {breakdown['subtitle']['tracks']} ({subtitle_savings})")
            logger.info(f"  Languages: {', '.join(languages)}")
        
        # Show what's being kept
        kept_audio = [t for t in tracks if t.type == 'audio' and t.index not in tracks_to_remove]
        kept_subs = [t for t in tracks if t.type == 'subtitle' and t.index not in tracks_to_remove]
        
        if kept_audio:
            languages = [f"{t.language or 'Unknown'}" + (f" ({t.title})" if t.title else "") 
                        for t in kept_audio]
            logger.info(f"\nKeeping Audio Tracks:")
            logger.info(f"  Languages: {', '.join(languages)}")
        
        if kept_subs:
            languages = [f"{t.language or 'Unknown'}" + (f" ({t.title})" if t.title else "") 
                        for t in kept_subs]
            logger.info(f"Keeping Subtitle Tracks:")
            logger.info(f"  Languages: {', '.join(languages)}")
    
    def process_video(self, video_path: Path, process_audio: bool = True,
                     process_subtitles: bool = True, remove_audio_languages: List[str] = None,
                     keep_audio_languages: List[str] = None, remove_subtitle_languages: List[str] = None,
                     keep_subtitle_languages: List[str] = None):
        """Process a video file to manage audio and subtitle tracks based on language."""
        logger.info(f"Processing {video_path}")
        
        tracks = self.get_tracks(video_path)
        manager = TrackManager(tracks)
        
        logger.info(f"\nCurrent tracks:\n{manager.get_track_summary()}")
        
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
            logger.info(f"Would remove the following tracks from {video_path}:")
            for idx in tracks_to_remove:
                track = next(t for t in tracks if t.index == idx)
                logger.info(f"- {track.type.capitalize()} track {idx}: {track.language or 'Unknown'}")
            return
        
        mapping = ['-map', '0']  # Start with all streams
        for idx in tracks_to_remove:
            mapping.extend(['-map', f'-0:{idx}'])  # Remove specific streams
        
        with tempfile.NamedTemporaryFile(suffix=video_path.suffix, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                *mapping,
                '-c', 'copy',  # Stream copy (no re-encoding)
                str(temp_path)
            ]
            
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                shutil.move(str(temp_path), str(video_path))
                logger.info(f"Successfully processed {video_path}")
                
                logger.info("\nRemaining tracks:")
                self.list_tracks(video_path)
                
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to process {video_path}: {e.stderr}")
                if temp_path.exists():
                    temp_path.unlink()
                raise
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                raise