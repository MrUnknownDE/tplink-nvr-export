"""NVR API client for interacting with TP-Link Vigi NVR."""

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests
from tqdm import tqdm

from .auth import AuthenticationError, NVRAuthenticator
from .models import Channel, ExportJob, Recording


class NVRClient:
    """Client for TP-Link Vigi NVR API operations."""
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 20443,
        verify_ssl: bool = False,
    ):
        """
        Initialize NVR client.
        
        Args:
            host: NVR IP address or hostname
            username: Admin username
            password: Admin password
            port: OpenAPI port (default: 20443)
            verify_ssl: Whether to verify SSL certificates
        """
        self.host = host
        self.port = port
        self.base_url = f"https://{host}:{port}"
        self.auth = NVRAuthenticator(host, username, password, port, verify_ssl)
        self._session: Optional[requests.Session] = None
    
    @property
    def session(self) -> requests.Session:
        """Get authenticated HTTP session."""
        if self._session is None:
            self._session = self.auth.get_authenticated_session()
        return self._session
    
    def _api_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """
        Make an authenticated API request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for requests
            
        Returns:
            JSON response as dict
            
        Raises:
            NVRAPIError: If request fails
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(method, url, timeout=60, **kwargs)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("error_code", 0) != 0:
                error_msg = data.get("error_msg", "Unknown API error")
                raise NVRAPIError(f"API error: {error_msg}")
            
            return data
            
        except requests.RequestException as e:
            raise NVRAPIError(f"Request failed: {e}") from e
    
    def get_channels(self) -> list[Channel]:
        """
        Get list of camera channels configured on NVR.
        
        Returns:
            List of Channel objects
        """
        # Try the standard device/channels endpoint
        try:
            data = self._api_request("POST", "/api/v1/channels", json={"method": "get"})
            channels = []
            
            for ch_data in data.get("result", {}).get("channel_list", []):
                channels.append(Channel(
                    id=ch_data.get("channel_id", 0),
                    name=ch_data.get("channel_name", f"Channel {ch_data.get('channel_id', 0)}"),
                    enabled=ch_data.get("enabled", True),
                ))
            
            return channels
            
        except NVRAPIError:
            # Fallback: try alternative endpoint structure
            data = self._api_request("POST", "/api/v1/device", json={"method": "getChannels"})
            channels = []
            
            for ch_data in data.get("result", {}).get("channels", []):
                channels.append(Channel(
                    id=ch_data.get("id", 0),
                    name=ch_data.get("name", f"Channel {ch_data.get('id', 0)}"),
                    enabled=ch_data.get("status", "on") == "on",
                ))
            
            return channels
    
    def search_recordings(
        self,
        channel_id: int,
        start_time: datetime,
        end_time: datetime,
        recording_type: str = "all",
    ) -> list[Recording]:
        """
        Search for recordings in a time range.
        
        Args:
            channel_id: Camera channel ID (1-based)
            start_time: Start of time range
            end_time: End of time range
            recording_type: Type filter ("all", "continuous", "motion", "alarm")
            
        Returns:
            List of Recording objects matching criteria
        """
        # Format times as expected by NVR API (typically Unix timestamp or ISO format)
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        type_map = {
            "all": 0,
            "continuous": 1,
            "motion": 2,
            "alarm": 4,
        }
        rec_type = type_map.get(recording_type, 0)
        
        # Try primary search endpoint
        try:
            data = self._api_request(
                "POST",
                "/api/v1/playback/search",
                json={
                    "method": "searchRecordings",
                    "channel_id": channel_id,
                    "start_time": start_ts,
                    "end_time": end_ts,
                    "record_type": rec_type,
                },
            )
        except NVRAPIError:
            # Fallback endpoint format
            data = self._api_request(
                "POST",
                "/api/v1/record/search",
                json={
                    "method": "search",
                    "params": {
                        "channel": channel_id,
                        "start": start_ts,
                        "end": end_ts,
                        "type": rec_type,
                    },
                },
            )
        
        recordings = []
        result = data.get("result", {})
        record_list = result.get("record_list", result.get("recordings", []))
        
        for rec_data in record_list:
            # Parse timestamps (could be Unix or string format)
            rec_start = self._parse_timestamp(rec_data.get("start_time", rec_data.get("start", 0)))
            rec_end = self._parse_timestamp(rec_data.get("end_time", rec_data.get("end", 0)))
            
            recordings.append(Recording(
                id=str(rec_data.get("record_id", rec_data.get("id", ""))),
                channel_id=channel_id,
                start_time=rec_start,
                end_time=rec_end,
                size_bytes=rec_data.get("size", rec_data.get("file_size", 0)),
                recording_type=rec_data.get("type", rec_data.get("record_type", "unknown")),
                file_path=rec_data.get("file_path", rec_data.get("path")),
            ))
        
        return recordings
    
    def _parse_timestamp(self, ts) -> datetime:
        """Parse timestamp from various formats."""
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        if isinstance(ts, str):
            # Try common formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    return datetime.strptime(ts, fmt)
                except ValueError:
                    continue
            # Try Unix timestamp as string
            return datetime.fromtimestamp(int(ts))
        return datetime.now()
    
    def download_recording(
        self,
        recording: Recording,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """
        Download a single recording to disk.
        
        Args:
            recording: Recording to download
            output_path: Directory or file path for output
            progress_callback: Optional callback(bytes_downloaded, total_bytes)
            
        Returns:
            Path to downloaded file
        """
        # Construct download URL
        if recording.file_path:
            download_url = f"{self.base_url}/api/v1/playback/download?path={recording.file_path}"
        else:
            download_url = (
                f"{self.base_url}/api/v1/playback/download"
                f"?record_id={recording.id}"
                f"&channel_id={recording.channel_id}"
            )
        
        # Determine output filename
        if output_path.is_dir():
            filename = self._generate_filename(recording)
            output_file = output_path / filename
        else:
            output_file = output_path
        
        # Ensure parent directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            response = self.session.get(download_url, stream=True, timeout=300)
            response.raise_for_status()
            
            # Get total size from headers or recording metadata
            total_size = int(response.headers.get("content-length", recording.size_bytes))
            
            downloaded = 0
            chunk_size = 8192
            
            with open(output_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            return output_file
            
        except requests.RequestException as e:
            raise NVRAPIError(f"Download failed: {e}") from e
    
    def _generate_filename(self, recording: Recording) -> str:
        """Generate a filename for a recording."""
        start_str = recording.start_time.strftime("%Y%m%d_%H%M%S")
        end_str = recording.end_time.strftime("%H%M%S")
        return f"ch{recording.channel_id}_{start_str}-{end_str}.mp4"
    
    def export_time_range(
        self,
        channel_id: int,
        start_time: datetime,
        end_time: datetime,
        output_dir: Path,
        recording_type: str = "all",
        show_progress: bool = True,
    ) -> list[Path]:
        """
        Export all recordings in a time range.
        
        Args:
            channel_id: Camera channel ID
            start_time: Start of time range
            end_time: End of time range
            output_dir: Directory to save recordings
            recording_type: Type filter
            show_progress: Whether to show progress bars
            
        Returns:
            List of paths to downloaded files
        """
        # Search for recordings
        recordings = self.search_recordings(channel_id, start_time, end_time, recording_type)
        
        if not recordings:
            return []
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        downloaded_files = []
        
        # Download with progress
        recordings_iter = tqdm(recordings, desc="Downloading", disable=not show_progress)
        
        for recording in recordings_iter:
            if show_progress:
                recordings_iter.set_postfix_str(f"Ch{recording.channel_id} {recording.start_time:%H:%M}")
            
            try:
                output_file = self.download_recording(recording, output_dir)
                downloaded_files.append(output_file)
            except NVRAPIError as e:
                if show_progress:
                    tqdm.write(f"Warning: Failed to download {recording}: {e}")
        
        return downloaded_files
    
    def close(self) -> None:
        """Close connections."""
        self.auth.close()
    
    def __enter__(self) -> "NVRClient":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class NVRAPIError(Exception):
    """Raised when NVR API operations fail."""
    pass
