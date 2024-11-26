from dataclasses import dataclass
from typing import List, Optional

@dataclass
class TrackInfo:
    index: int
    type: str  # 'audio' or 'subtitle'
    language: Optional[str]
    title: Optional[str]
    default: bool
    forced: bool

class TrackManager:
    def __init__(self, tracks: List[TrackInfo]):
        self.tracks = tracks
    
    def filter_tracks_by_type(self, track_type: str, remove_languages: List[str] = None,
                            keep_languages: List[str] = None) -> List[int]:
        """Return indices of tracks to remove based on language criteria for a specific track type."""
        if not (remove_languages or keep_languages):
            return []
            
        tracks_to_remove = []
        type_tracks = [t for t in self.tracks if t.type == track_type]
        
        for track in type_tracks:
            track_lang = track.language.lower() if track.language else 'und'
            
            if remove_languages and track_lang in remove_languages:
                tracks_to_remove.append(track.index)
            elif keep_languages and track_lang not in keep_languages:
                tracks_to_remove.append(track.index)
                
        return tracks_to_remove
    
    def get_track_summary(self) -> str:
        """Generate a human-readable summary of tracks."""
        summary = []
        
        for track in self.tracks:
            track_type = track.type.capitalize()
            lang = track.language or 'Unknown'
            title = f" ({track.title})" if track.title else ""
            flags = []
            
            if track.default:
                flags.append("default")
            if track.forced:
                flags.append("forced")
                
            flags_str = f" ({', '.join(flags)})" if flags else ""
            
            summary.append(f"Track {track.index}: {track_type} - {lang}{title}{flags_str}")
            
        return "\n".join(summary)