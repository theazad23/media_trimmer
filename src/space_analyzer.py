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
        video_path = Path(video_path).resolve()
        
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-print_format', 'json',
            '-show_streams',
            '-show_format',
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
            
            if not data.get('format'):
                raise RuntimeError("No format information found in the video file")
                
            duration = float(data.get('format', {}).get('duration', 0))
            if duration == 0:
                raise RuntimeError("Could not determine video duration")
                
            stream_sizes = []
            for stream in data.get('streams', []):
                if stream['codec_type'] not in ('audio', 'subtitle'):
                    continue
                    
                # Try multiple ways to get bitrate information
                bit_rate = None
                if 'bit_rate' in stream:
                    bit_rate = stream['bit_rate']
                elif 'tags' in stream:
                    tags = stream['tags']
                    bit_rate = tags.get('BPS') or tags.get('bit_rate')
                    
                if bit_rate:
                    try:
                        size_bytes = int(float(bit_rate) * duration / 8)
                        stream_sizes.append(StreamSize(
                            type=stream['codec_type'],
                            language=stream.get('tags', {}).get('language', 'und'),
                            size_bytes=size_bytes
                        ))
                    except (ValueError, TypeError):
                        logger.warning(f"Could not calculate size for {stream['codec_type']} stream")
                        
            return stream_sizes
            
        except subprocess.CalledProcessError as e:
            error_output = e.stderr.strip() if e.stderr else "No error output available"
            raise RuntimeError(f"Failed to analyze video streams: {error_output}")
        except json.JSONDecodeError:
            raise RuntimeError("Failed to parse ffprobe output")
        except Exception as e:
            raise RuntimeError(f"Unexpected error analyzing streams: {str(e)}")

    def analyze_savings(self, video_path: Path, **kwargs) -> dict:
        """Analyze potential space savings from removing tracks."""
        video_path = Path(video_path).resolve()
        if not video_path.exists():
            raise RuntimeError(f"File not found: {video_path}")
            
        stream_sizes = self.get_stream_sizes(video_path)
        total_savings = 0
        savings_breakdown = {
            'audio': {'bytes': 0, 'tracks': 0},
            'subtitle': {'bytes': 0, 'tracks': 0}
        }
        
        for stream in stream_sizes:
            if not kwargs.get('process_audio') and stream.type == 'audio':
                continue
            if not kwargs.get('process_subtitles') and stream.type == 'subtitle':
                continue
            
            remove_langs = kwargs.get('remove_audio_languages') if stream.type == 'audio' else kwargs.get('remove_subtitle_languages')
            keep_langs = kwargs.get('keep_audio_languages') if stream.type == 'audio' else kwargs.get('keep_subtitle_languages')
            
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