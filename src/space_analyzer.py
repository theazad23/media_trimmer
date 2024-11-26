from pathlib import Path
from typing import Dict, List, NamedTuple
import json
import subprocess
import logging

logger = logging.getLogger(__name__)

class StreamSize(NamedTuple):
    type: str
    language: str
    size_bytes: int

class SpaceAnalyzer:
    @staticmethod
    def get_stream_sizes(video_path: Path) -> List[StreamSize]:
        """Analyze video file to get the size of each stream."""
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-show_format',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get stream info: {result.stderr}")
            
        data = json.loads(result.stdout)
        duration = float(data.get('format', {}).get('duration', 0))
        if duration == 0:
            return []
            
        stream_sizes = []
        for stream in data.get('streams', []):
            if stream['codec_type'] not in ('audio', 'subtitle'):
                continue
                
            bit_rate = stream.get('bit_rate')
            if not bit_rate:
                tags = stream.get('tags', {})
                bit_rate = tags.get('BPS') or tags.get('bit_rate')
            
            if bit_rate:
                size_bytes = int(float(bit_rate) * duration / 8)
                stream_sizes.append(StreamSize(
                    type=stream['codec_type'],
                    language=stream.get('tags', {}).get('language', 'und'),
                    size_bytes=size_bytes
                ))
        
        return stream_sizes

    def analyze_savings(self, video_path: Path, process_audio: bool = True,
                       process_subtitles: bool = True, remove_audio_languages: List[str] = None,
                       keep_audio_languages: List[str] = None, remove_subtitle_languages: List[str] = None,
                       keep_subtitle_languages: List[str] = None) -> Dict:
        """Analyze potential space savings from removing tracks."""
        stream_sizes = self.get_stream_sizes(video_path)
        total_savings = 0
        savings_breakdown = {
            'audio': {'bytes': 0, 'tracks': 0},
            'subtitle': {'bytes': 0, 'tracks': 0}
        }
        
        for stream in stream_sizes:
            if not process_audio and stream.type == 'audio':
                continue
            if not process_subtitles and stream.type == 'subtitle':
                continue
            
            remove_langs = remove_audio_languages if stream.type == 'audio' else remove_subtitle_languages
            keep_langs = keep_audio_languages if stream.type == 'audio' else keep_subtitle_languages
            
            should_remove = False
            if remove_langs and stream.language in remove_langs:
                should_remove = True
            elif keep_langs and stream.language not in keep_langs:
                should_remove = True
                
            if should_remove:
                total_savings += stream.size_bytes
                savings_breakdown[stream.type]['bytes'] += stream.size_bytes
                savings_breakdown[stream.type]['tracks'] += 1
        
        return {
            'total_savings': total_savings,
            'breakdown': savings_breakdown,
            'original_size': Path(video_path).stat().st_size
        }

def format_size(size_bytes: int) -> str:
    """Format byte size to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"