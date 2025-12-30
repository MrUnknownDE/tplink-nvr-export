"""Data models for NVR recordings and channels."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Channel:
    """Represents a camera channel on the NVR."""
    
    id: int
    name: str
    enabled: bool = True
    
    def __str__(self) -> str:
        return f"Channel {self.id}: {self.name}"


@dataclass
class Recording:
    """Represents a video recording segment."""
    
    id: str
    channel_id: int
    start_time: datetime
    end_time: datetime
    size_bytes: int
    recording_type: str  # "continuous", "motion", "alarm", etc.
    file_path: Optional[str] = None
    
    @property
    def duration_seconds(self) -> int:
        """Get recording duration in seconds."""
        return int((self.end_time - self.start_time).total_seconds())
    
    @property
    def size_mb(self) -> float:
        """Get recording size in megabytes."""
        return self.size_bytes / (1024 * 1024)
    
    def __str__(self) -> str:
        return (
            f"Recording {self.id}: Ch{self.channel_id} "
            f"{self.start_time.strftime('%Y-%m-%d %H:%M')} - "
            f"{self.end_time.strftime('%H:%M')} ({self.size_mb:.1f} MB)"
        )


@dataclass  
class ExportJob:
    """Represents an export job with multiple recordings."""
    
    channel_id: int
    start_time: datetime
    end_time: datetime
    recordings: list[Recording]
    output_dir: str
    
    @property
    def total_size_bytes(self) -> int:
        """Total size of all recordings."""
        return sum(r.size_bytes for r in self.recordings)
    
    @property
    def total_duration_seconds(self) -> int:
        """Total duration of all recordings."""
        return sum(r.duration_seconds for r in self.recordings)
