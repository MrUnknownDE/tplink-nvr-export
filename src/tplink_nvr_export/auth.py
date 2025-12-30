"""Authentication module for TP-Link Vigi NVR OpenAPI."""

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth


@dataclass
class AuthSession:
    """Holds authentication session data."""
    
    access_token: str
    token_type: str
    expires_at: float
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return time.time() >= self.expires_at
    
    @property
    def authorization_header(self) -> str:
        """Get Authorization header value."""
        return f"{self.token_type} {self.access_token}"


class NVRAuthenticator:
    """Handles authentication with TP-Link Vigi NVR OpenAPI."""
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 20443,
        verify_ssl: bool = False,
    ):
        """
        Initialize authenticator.
        
        Args:
            host: NVR IP address or hostname
            username: Admin username
            password: Admin password
            port: OpenAPI port (default: 20443)
            verify_ssl: Whether to verify SSL certificates
        """
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{host}:{port}"
        self._session: Optional[AuthSession] = None
        self._http_session = requests.Session()
        self._http_session.verify = verify_ssl
        
        # Suppress SSL warnings if not verifying
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    @property
    def session(self) -> Optional[AuthSession]:
        """Get current auth session, refreshing if expired."""
        if self._session is None or self._session.is_expired:
            self._session = self._authenticate()
        return self._session
    
    def _authenticate(self) -> AuthSession:
        """
        Authenticate with NVR and obtain access token.
        
        The NVR uses HTTP Digest Authentication for the initial login,
        then returns a bearer token for subsequent requests.
        
        Returns:
            AuthSession with access token
            
        Raises:
            AuthenticationError: If authentication fails
        """
        login_url = f"{self.base_url}/api/v1/login"
        
        try:
            # First attempt with Digest Auth
            response = self._http_session.post(
                login_url,
                auth=HTTPDigestAuth(self.username, self.password),
                json={"method": "login"},
                timeout=30,
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("error_code", 0) != 0:
                error_msg = data.get("error_msg", "Unknown error")
                raise AuthenticationError(f"Login failed: {error_msg}")
            
            result = data.get("result", {})
            access_token = result.get("stok", "")
            
            if not access_token:
                raise AuthenticationError("No access token in response")
            
            # Token typically expires in 1 hour, refresh at 50 minutes
            expires_at = time.time() + (50 * 60)
            
            return AuthSession(
                access_token=access_token,
                token_type="Bearer",
                expires_at=expires_at,
            )
            
        except requests.RequestException as e:
            raise AuthenticationError(f"Connection failed: {e}") from e
    
    def get_authenticated_session(self) -> requests.Session:
        """
        Get a requests session with authentication headers configured.
        
        Returns:
            Configured requests.Session
        """
        session = self.session
        if session:
            self._http_session.headers.update({
                "Authorization": session.authorization_header,
            })
        return self._http_session
    
    def close(self) -> None:
        """Close the HTTP session."""
        self._http_session.close()
    
    def __enter__(self) -> "NVRAuthenticator":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class AuthenticationError(Exception):
    """Raised when authentication with NVR fails."""
    pass
