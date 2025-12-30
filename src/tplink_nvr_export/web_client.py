"""Web Interface API client for TP-Link Vigi NVR.

Uses the stok-based authentication for the /ds endpoint,
which provides access to recordings and playback.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from tqdm import tqdm

from .debug import log_debug, log_error, log_request, log_response, is_debug_enabled
from .models import Channel, Recording


@dataclass
class StokSession:
    """Holds stok session data."""
    
    stok: str
    expires_at: float
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired (valid ~30 min)."""
        return time.time() >= self.expires_at


class WebClient:
    """Client for TP-Link Vigi NVR Web Interface API.
    
    Uses /stok={token}/ds endpoint for all operations.
    This provides access to recordings, playback, and other features
    not available via the OpenAPI.
    """
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = False,
    ):
        """
        Initialize Web client.
        
        Args:
            host: NVR IP address or hostname
            username: Admin username
            password: Admin password
            port: Web interface port (default: 443)
            verify_ssl: Whether to verify SSL certificates
        """
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{host}" if port == 443 else f"https://{host}:{port}"
        self._session: Optional[StokSession] = None
        self._http_session = requests.Session()
        self._http_session.verify = verify_ssl
        
        # Suppress SSL warnings if not verifying
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        log_debug(f"WebClient initialized for {host}:{port}")
    
    @property
    def stok(self) -> str:
        """Get current stok token, refreshing if expired."""
        if self._session is None or self._session.is_expired:
            self._session = self._login()
        return self._session.stok
    
    def _hash_password(self, password: str) -> str:
        """Hash password for login. TP-Link uses MD5."""
        return hashlib.md5(password.encode()).hexdigest()
    
    def _login(self) -> StokSession:
        """
        Login to NVR web interface and obtain stok token.
        
        Returns:
            StokSession with stok token
            
        Raises:
            WebClientError: If login fails
        """
        login_url = f"{self.base_url}/"
        
        log_debug(f"Logging in to {login_url}")
        
        try:
            # First, try standard TP-Link login format
            # The login endpoint is usually POST to / with form data
            login_data = {
                "method": "do",
                "login": {
                    "username": self.username,
                    "password": self._hash_password(self.password),
                }
            }
            
            log_request("POST", login_url, body=login_data)
            
            response = self._http_session.post(
                login_url,
                json=login_data,
                timeout=30,
            )
            
            log_response(response.status_code, dict(response.headers), 
                        response.json() if response.content else None)
            
            if response.status_code == 200:
                data = response.json()
                stok = data.get("stok", "")
                
                if stok:
                    log_debug(f"Got stok token: {stok[:20]}...")
                    # Token valid for ~25 minutes (refresh before 30)
                    expires_at = time.time() + (25 * 60)
                    return StokSession(stok=stok, expires_at=expires_at)
            
            # Try alternative login format
            alt_login_data = {
                "username": self.username,
                "password": self._hash_password(self.password),
            }
            
            log_debug("Trying alternative login format")
            log_request("POST", login_url, body=alt_login_data)
            
            response = self._http_session.post(
                login_url,
                data=alt_login_data,
                timeout=30,
            )
            
            log_response(response.status_code, dict(response.headers),
                        response.text[:500] if response.text else None)
            
            # Check for stok in response
            try:
                data = response.json()
                stok = data.get("stok", data.get("result", {}).get("stok", ""))
                if stok:
                    expires_at = time.time() + (25 * 60)
                    return StokSession(stok=stok, expires_at=expires_at)
            except ValueError:
                pass
            
            raise WebClientError("Could not obtain stok token from login response")
            
        except requests.RequestException as e:
            log_error("Login failed", e)
            raise WebClientError(f"Login failed: {e}") from e
    
    def _ds_request(
        self,
        data: dict,
    ) -> dict:
        """
        Make a request to the /ds endpoint.
        
        Args:
            data: Request data (method, params, etc.)
            
        Returns:
            JSON response as dict
        """
        url = f"{self.base_url}/stok={self.stok}/ds"
        
        log_request("POST", url, body=data)
        
        try:
            response = self._http_session.post(
                url,
                json=data,
                timeout=60,
            )
            
            try:
                response_data = response.json()
            except ValueError:
                response_data = {"raw": response.text[:500] if response.text else "empty"}
            
            log_response(response.status_code, dict(response.headers), response_data)
            
            response.raise_for_status()
            
            # Check for error in response
            error_code = response_data.get("error_code", 0)
            if error_code != 0:
                error_msg = response_data.get("error_msg", f"Error code: {error_code}")
                raise WebClientError(f"API error: {error_msg}")
            
            return response_data
            
        except requests.RequestException as e:
            log_error(f"Request to /ds failed", e)
            raise WebClientError(f"Request failed: {e}") from e
    
    def get_channels(self) -> list[Channel]:
        """Get list of camera channels."""
        log_debug("Getting channels via /ds")
        
        # Try different methods to get channel list
        methods_to_try = [
            {"method": "get", "channel": {"table": ["channel"]}},
            {"method": "get", "device": {"name": ["device_info"]}},
            {"method": "get", "channel_info": {}},
            {"method": "do", "channel": {"action": "list"}},
        ]
        
        for method_data in methods_to_try:
            try:
                data = self._ds_request(method_data)
                
                # Try to find channels in response
                channels = []
                
                # Look for channel data in various places
                channel_data = (
                    data.get("channel", {}).get("table", {}).get("channel", []) or
                    data.get("channel", []) or
                    data.get("channels", []) or
                    data.get("result", {}).get("channels", []) or
                    []
                )
                
                if channel_data:
                    for i, ch in enumerate(channel_data):
                        if isinstance(ch, dict):
                            channels.append(Channel(
                                id=ch.get("id", ch.get("channel_id", i + 1)),
                                name=ch.get("name", ch.get("channel_name", f"Channel {i + 1}")),
                                enabled=ch.get("enabled", True),
                            ))
                    
                    if channels:
                        return channels
                        
            except WebClientError as e:
                log_debug(f"Method failed: {e}")
                continue
        
        # Return default channels if API doesn't provide them
        log_debug("Using default channels 1-32")
        return [Channel(id=i, name=f"Channel {i}", enabled=True) for i in range(1, 33)]
    
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
            channel_id: Camera channel ID
            start_time: Start of time range
            end_time: End of time range
            recording_type: Type filter
            
        Returns:
            List of Recording objects
        """
        start_str = start_time.strftime("%Y%m%d")
        end_str = end_time.strftime("%Y%m%d")
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        log_debug(f"Searching recordings: ch={channel_id}, {start_time} to {end_time}")
        
        # Try different search methods
        methods_to_try = [
            {
                "method": "get",
                "playback": {
                    "table": ["search"],
                    "search": {
                        "channel": channel_id,
                        "start_date": start_str,
                        "end_date": end_str,
                    }
                }
            },
            {
                "method": "do",
                "playback": {
                    "action": "search",
                    "channel": channel_id,
                    "start_time": start_ts,
                    "end_time": end_ts,
                }
            },
            {
                "method": "get",
                "record": {
                    "table": ["search"],
                    "search": {
                        "channel_id": channel_id,
                        "start": start_ts,
                        "end": end_ts,
                    }
                }
            },
            {
                "method": "do",
                "record": {
                    "action": "search",
                    "channel": channel_id,
                    "start_date": start_str,
                    "end_date": end_str,
                }
            },
        ]
        
        recordings = []
        
        for method_data in methods_to_try:
            try:
                log_debug(f"Trying: {json.dumps(method_data)[:100]}")
                data = self._ds_request(method_data)
                
                # Log full response for debugging
                if is_debug_enabled():
                    log_debug(f"Full response: {json.dumps(data, indent=2, default=str)[:1500]}")
                
                # Look for recordings in various places
                record_list = (
                    data.get("playback", {}).get("table", {}).get("search", []) or
                    data.get("playback", {}).get("search", []) or
                    data.get("record", {}).get("table", {}).get("search", []) or
                    data.get("record", {}).get("search", []) or
                    data.get("result", {}).get("records", []) or
                    data.get("records", []) or
                    data.get("list", []) or
                    []
                )
                
                log_debug(f"Found {len(record_list)} records in response")
                
                if record_list:
                    for rec in record_list:
                        try:
                            rec_start = self._parse_time(rec.get("start", rec.get("start_time", 0)))
                            rec_end = self._parse_time(rec.get("end", rec.get("end_time", 0)))
                            
                            recordings.append(Recording(
                                id=str(rec.get("id", rec.get("record_id", ""))),
                                channel_id=channel_id,
                                start_time=rec_start,
                                end_time=rec_end,
                                size_bytes=rec.get("size", rec.get("file_size", 0)),
                                recording_type=str(rec.get("type", "unknown")),
                                file_path=rec.get("path", rec.get("file_path")),
                            ))
                        except Exception as e:
                            log_debug(f"Error parsing record: {e}")
                            continue
                    
                    if recordings:
                        return recordings
                        
            except WebClientError as e:
                log_debug(f"Method failed: {e}")
                continue
        
        return recordings
    
    def _parse_time(self, t) -> datetime:
        """Parse time from various formats."""
        if isinstance(t, (int, float)) and t > 0:
            return datetime.fromtimestamp(t)
        if isinstance(t, str):
            for fmt in ["%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    return datetime.strptime(t, fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromtimestamp(int(t))
            except:
                pass
        return datetime.now()
    
    def download_recording(
        self,
        recording: Recording,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """Download a recording to disk."""
        # Build download URL
        if recording.file_path:
            download_url = f"{self.base_url}/stok={self.stok}/ds?download={recording.file_path}"
        else:
            download_url = f"{self.base_url}/stok={self.stok}/ds?download&channel={recording.channel_id}&id={recording.id}"
        
        log_debug(f"Downloading from: {download_url}")
        
        # Determine output filename
        if output_path.is_dir():
            start_str = recording.start_time.strftime("%Y%m%d_%H%M%S")
            end_str = recording.end_time.strftime("%H%M%S")
            filename = f"ch{recording.channel_id}_{start_str}-{end_str}.mp4"
            output_file = output_path / filename
        else:
            output_file = output_path
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            response = self._http_session.get(download_url, stream=True, timeout=300)
            response.raise_for_status()
            
            total_size = int(response.headers.get("content-length", recording.size_bytes or 0))
            
            downloaded = 0
            with open(output_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            log_debug(f"Downloaded {downloaded} bytes to {output_file}")
            return output_file
            
        except requests.RequestException as e:
            log_error(f"Download failed", e)
            raise WebClientError(f"Download failed: {e}") from e
    
    def export_time_range(
        self,
        channel_id: int,
        start_time: datetime,
        end_time: datetime,
        output_dir: Path,
        recording_type: str = "all",
        show_progress: bool = True,
    ) -> list[Path]:
        """Export all recordings in a time range."""
        recordings = self.search_recordings(channel_id, start_time, end_time, recording_type)
        
        if not recordings:
            return []
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        downloaded_files = []
        recordings_iter = tqdm(recordings, desc="Downloading", disable=not show_progress)
        
        for recording in recordings_iter:
            if show_progress:
                recordings_iter.set_postfix_str(f"Ch{recording.channel_id} {recording.start_time:%H:%M}")
            
            try:
                output_file = self.download_recording(recording, output_dir)
                downloaded_files.append(output_file)
            except WebClientError as e:
                if show_progress:
                    tqdm.write(f"Warning: Failed to download {recording}: {e}")
        
        return downloaded_files
    
    def close(self) -> None:
        """Close the HTTP session."""
        self._http_session.close()
    
    def __enter__(self) -> "WebClient":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class WebClientError(Exception):
    """Raised when web interface operations fail."""
    pass
