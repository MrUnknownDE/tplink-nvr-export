"""Authentication module for TP-Link Vigi NVR OpenAPI."""

import hashlib
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests


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
    """Handles authentication with TP-Link Vigi NVR OpenAPI.
    
    The NVR uses HTTP Digest Authentication with SHA-256 to obtain an access_token.
    Endpoint: /openapi/token
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
    
    def _calculate_digest_response(
        self,
        method: str,
        uri: str,
        nonce: str,
        realm: str,
        algorithm: str = "SHA-256",
    ) -> str:
        """
        Calculate Digest Authentication response.
        
        A1 = SHA256(username:realm:password)
        A2 = SHA256(method:uri)
        response = SHA256(A1:nonce:A2)
        """
        if algorithm.upper() in ("SHA-256", "SHA256"):
            hash_func = hashlib.sha256
        else:
            hash_func = hashlib.md5
        
        # Calculate A1
        a1_string = f"{self.username}:{realm}:{self.password}"
        a1 = hash_func(a1_string.encode()).hexdigest()
        
        # Calculate A2
        a2_string = f"{method}:{uri}"
        a2 = hash_func(a2_string.encode()).hexdigest()
        
        # Calculate response
        response_string = f"{a1}:{nonce}:{a2}"
        response = hash_func(response_string.encode()).hexdigest()
        
        return response
    
    def _parse_www_authenticate(self, header: str) -> dict:
        """Parse WWW-Authenticate header into dict."""
        # Example: Digest realm="VIGI", nonce="abc123", algorithm=SHA-256
        result = {}
        # Remove 'Digest ' prefix
        if header.lower().startswith("digest "):
            header = header[7:]
        
        # Parse key=value pairs
        import re
        pattern = r'(\w+)=(?:"([^"]+)"|([^\s,]+))'
        for match in re.finditer(pattern, header):
            key = match.group(1)
            value = match.group(2) or match.group(3)
            result[key] = value
        
        return result
    
    def _authenticate(self) -> AuthSession:
        """
        Authenticate with NVR and obtain access token.
        
        1. GET /openapi/token without auth to get nonce
        2. Calculate digest response
        3. GET /openapi/token with Authorization header
        4. Extract access_token from response
        
        Returns:
            AuthSession with access token
            
        Raises:
            AuthenticationError: If authentication fails
        """
        token_url = f"{self.base_url}/openapi/token"
        uri = "/openapi/token"
        
        try:
            # Step 1: Initial request to get nonce
            response = self._http_session.get(token_url, timeout=30)
            
            if response.status_code != 401:
                raise AuthenticationError(
                    f"Expected 401 for initial auth, got {response.status_code}"
                )
            
            # Parse WWW-Authenticate header
            www_auth = response.headers.get("WWW-Authenticate", "")
            if not www_auth:
                raise AuthenticationError("No WWW-Authenticate header in response")
            
            auth_params = self._parse_www_authenticate(www_auth)
            nonce = auth_params.get("nonce", "")
            realm = auth_params.get("realm", "VIGI")
            algorithm = auth_params.get("algorithm", "SHA-256")
            
            if not nonce:
                raise AuthenticationError("No nonce in WWW-Authenticate header")
            
            # Step 2: Calculate digest response
            digest_response = self._calculate_digest_response(
                method="GET",
                uri=uri,
                nonce=nonce,
                realm=realm,
                algorithm=algorithm,
            )
            
            # Step 3: Build Authorization header
            auth_header = (
                f'Digest username="{self.username}", '
                f'realm="{realm}", '
                f'nonce="{nonce}", '
                f'uri="{uri}", '
                f'algorithm={algorithm}, '
                f'response="{digest_response}"'
            )
            
            # Step 4: Authenticated request
            response = self._http_session.get(
                token_url,
                headers={"Authorization": auth_header},
                timeout=30,
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Extract access_token
            access_token = data.get("access_token", data.get("token", ""))
            
            if not access_token:
                # Try to get from result object
                result = data.get("result", {})
                access_token = result.get("access_token", result.get("stok", ""))
            
            if not access_token:
                raise AuthenticationError(f"No access token in response: {data}")
            
            # URL decode the token
            access_token = urllib.parse.unquote(access_token)
            
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
