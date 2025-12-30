"""NVR API client for interacting with TP-Link Vigi NVR."""

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests
from tqdm import tqdm

from .auth import AuthenticationError, NVRAuthenticator
from .debug import log_debug, log_error, log_request, log_response, is_debug_enabled
from .models import Channel, ExportJob, Recording


class NVRClient:
    """Client for TP-Link Vigi NVR OpenAPI operations.
    
    Base endpoint: /openapi/
    Authentication: Bearer token from /openapi/token
    """
    
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
        log_debug(f"NVRClient initialized for {host}:{port}")
    
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
            endpoint: API endpoint path (will be prefixed with /openapi/)
            **kwargs: Additional arguments for requests
            
        Returns:
            JSON response as dict
            
        Raises:
            NVRAPIError: If request fails
        """
        # Ensure endpoint starts with /openapi/
        if not endpoint.startswith("/openapi/"):
            endpoint = f"/openapi/{endpoint.lstrip('/')}"
        
        url = f"{self.base_url}{endpoint}"
        
        # Log request
        log_request(method, url, kwargs.get('headers'), kwargs.get('json'))
        
        try:
            response = self.session.request(method, url, timeout=60, **kwargs)
            
            # Log response
            try:
                response_data = response.json() if response.content else {}
            except ValueError:
                response_data = {"raw": response.text[:500] if response.text else "empty"}
            
            log_response(response.status_code, dict(response.headers), response_data)
            
            response.raise_for_status()
            
            # Some endpoints might return empty response
            if not response.content:
                return {}
            
            data = response.json()
            
            # Check for error in response
            error_code = data.get("error_code", data.get("errorCode", 0))
            if error_code != 0:
                error_msg = data.get("error_msg", data.get("errorMsg", "Unknown API error"))
                raise NVRAPIError(f"API error {error_code}: {error_msg}")
            
            return data
            
        except requests.RequestException as e:
            log_error(f"Request to {endpoint} failed", e)
            raise NVRAPIError(f"Request failed: {e}") from e
    
    def get_channels(self) -> list[Channel]:
        """
        Get list of camera channels configured on NVR.
        
        Returns:
            List of Channel objects
        """
        channels = []
        
        # Try different endpoint patterns
        endpoints_to_try = [
            ("GET", "added_devices"),
            ("GET", "channels"),
            ("POST", "channels", {"method": "get"}),
            ("GET", "device/channels"),
        ]
        
        log_debug(f"Trying {len(endpoints_to_try)} endpoint patterns for channels")
        
        for endpoint_info in endpoints_to_try:
            try:
                method = endpoint_info[0]
                endpoint = endpoint_info[1]
                json_data = endpoint_info[2] if len(endpoint_info) > 2 else None
                
                log_debug(f"Trying endpoint: {method} {endpoint}")
                
                if json_data:
                    data = self._api_request(method, endpoint, json=json_data)
                else:
                    data = self._api_request(method, endpoint)
                
                log_debug(f"Response keys: {list(data.keys()) if data else 'empty'}")
                
                # Parse response - try different structures
                channel_list = (
                    data.get("result", {}).get("channel_list", []) or
                    data.get("result", {}).get("channels", []) or
                    data.get("result", {}).get("devices", []) or
                    data.get("channel_list", []) or
                    data.get("channels", []) or
                    data.get("devices", []) or
                    []
                )
                
                log_debug(f"Found {len(channel_list)} channels in response")
                
                if channel_list:
                    for ch_data in channel_list:
                        channels.append(Channel(
                            id=ch_data.get("channel_id", ch_data.get("id", ch_data.get("channelId", 0))),
                            name=ch_data.get("channel_name", ch_data.get("name", ch_data.get("deviceName", f"Channel"))),
                            enabled=ch_data.get("enabled", ch_data.get("status", "on") == "on"),
                        ))
                    return channels
                    
            except NVRAPIError as e:
                log_debug(f"Endpoint {endpoint} failed: {e}")
                continue
        
        # If no channels found via API, return default channels 1-8
        log_debug("No channels found via API, returning defaults 1-8")
        if not channels:
            for i in range(1, 9):
                channels.append(Channel(id=i, name=f"Channel {i}", enabled=True))
        
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
        # Format times as expected by NVR API
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        # ISO format alternative
        start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%S")
        end_iso = end_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        log_debug(f"Searching recordings: channel={channel_id}, start={start_time}, end={end_time}")
        log_debug(f"Timestamps: start_ts={start_ts}, end_ts={end_ts}")
        
        type_map = {
            "all": 0,
            "continuous": 1,
            "motion": 2,
            "alarm": 4,
        }
        rec_type = type_map.get(recording_type, 0)
        
        recordings = []
        
        # Try different endpoint patterns
        endpoints_to_try = [
            ("POST", "playback/search", {
                "channelId": channel_id,
                "startTime": start_ts,
                "endTime": end_ts,
                "recordType": rec_type,
            }),
            ("POST", "record/search", {
                "channel": channel_id,
                "start": start_ts,
                "end": end_ts,
                "type": rec_type,
            }),
            ("GET", f"playback/search?channelId={channel_id}&startTime={start_ts}&endTime={end_ts}"),
            ("POST", "search", {
                "method": "searchRecordings",
                "params": {
                    "channel_id": channel_id,
                    "start_time": start_iso,
                    "end_time": end_iso,
                }
            }),
        ]
        
        log_debug(f"Trying {len(endpoints_to_try)} endpoint patterns for recordings")
        
        for endpoint_info in endpoints_to_try:
            try:
                method = endpoint_info[0]
                endpoint = endpoint_info[1]
                json_data = endpoint_info[2] if len(endpoint_info) > 2 and isinstance(endpoint_info[2], dict) else None
                
                log_debug(f"Trying endpoint: {method} {endpoint}")
                
                if json_data:
                    data = self._api_request(method, endpoint, json=json_data)
                else:
                    data = self._api_request(method, endpoint)
                
                log_debug(f"Response keys: {list(data.keys()) if data else 'empty'}")
                
                # Log full response structure for debugging
                if is_debug_enabled():
                    import json as json_module
                    log_debug(f"Full response: {json_module.dumps(data, indent=2, default=str)[:1000]}")
                
                # Parse response - try different structures
                result = data.get("result", data)
                record_list = (
                    result.get("record_list", []) or
                    result.get("recordings", []) or
                    result.get("recordList", []) or
                    result.get("items", []) or
                    result.get("searchResult", []) or
                    result.get("list", []) or
                    []
                )
                
                log_debug(f"Found {len(record_list)} recordings in response")
                
                if record_list:
                    for rec_data in record_list:
                        log_debug(f"Recording data: {rec_data}")
                        rec_start = self._parse_timestamp(
                            rec_data.get("start_time", rec_data.get("startTime", rec_data.get("start", 0)))
                        )
                        rec_end = self._parse_timestamp(
                            rec_data.get("end_time", rec_data.get("endTime", rec_data.get("end", 0)))
                        )
                        
                        recordings.append(Recording(
                            id=str(rec_data.get("record_id", rec_data.get("recordId", rec_data.get("id", "")))),
                            channel_id=channel_id,
                            start_time=rec_start,
                            end_time=rec_end,
                            size_bytes=rec_data.get("size", rec_data.get("fileSize", rec_data.get("file_size", 0))),
                            recording_type=str(rec_data.get("type", rec_data.get("recordType", rec_data.get("record_type", "unknown")))),
                            file_path=rec_data.get("file_path", rec_data.get("filePath", rec_data.get("path"))),
                        ))
                    return recordings
                    
            except NVRAPIError as e:
                log_debug(f"Endpoint {endpoint} failed: {e}")
                continue
        
        log_debug("No recordings found with any endpoint pattern")
        return recordings
    
    def _parse_timestamp(self, ts) -> datetime:
        """Parse timestamp from various formats."""
        if isinstance(ts, (int, float)):
            if ts > 0:
                return datetime.fromtimestamp(ts)
        if isinstance(ts, str):
            # Try common formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]:
                try:
                    return datetime.strptime(ts, fmt)
                except ValueError:
                    continue
            # Try Unix timestamp as string
            try:
                return datetime.fromtimestamp(int(ts))
            except (ValueError, OSError):
                pass
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
        # Try different download URL patterns
        download_urls = []
        
        if recording.file_path:
            download_urls.append(f"{self.base_url}/openapi/playback/download?path={recording.file_path}")
            download_urls.append(f"{self.base_url}/openapi/download?filePath={recording.file_path}")
        
        download_urls.extend([
            f"{self.base_url}/openapi/playback/download?recordId={recording.id}&channelId={recording.channel_id}",
            f"{self.base_url}/openapi/record/download?id={recording.id}",
            f"{self.base_url}/openapi/download?recordId={recording.id}",
        ])
        
        log_debug(f"Download URLs to try: {download_urls}")
        
        # Determine output filename
        if output_path.is_dir():
            filename = self._generate_filename(recording)
            output_file = output_path / filename
        else:
            output_file = output_path
        
        # Ensure parent directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        last_error = None
        for download_url in download_urls:
            try:
                log_debug(f"Trying download from: {download_url}")
                response = self.session.get(download_url, stream=True, timeout=300)
                
                log_debug(f"Download response: {response.status_code}, Content-Type: {response.headers.get('content-type')}")
                
                response.raise_for_status()
                
                # Check if response is actually video data
                content_type = response.headers.get("content-type", "")
                if "json" in content_type or "html" in content_type:
                    # This is an error response, try next URL
                    log_debug(f"Got non-video response, trying next URL")
                    continue
                
                # Get total size from headers or recording metadata
                total_size = int(response.headers.get("content-length", recording.size_bytes or 0))
                
                downloaded = 0
                chunk_size = 8192
                
                with open(output_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_size)
                
                log_debug(f"Downloaded {downloaded} bytes to {output_file}")
                return output_file
                
            except requests.RequestException as e:
                log_error(f"Download from {download_url} failed", e)
                last_error = e
                continue
        
        raise NVRAPIError(f"Download failed after trying all URLs: {last_error}")
    
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
