"""Debug logging utilities for NVR Export."""

import json
import logging
import sys
from datetime import datetime
from typing import Any


# Create logger
logger = logging.getLogger("nvr_export")


def setup_debug_logging(enabled: bool = False, log_file: str = None) -> None:
    """
    Setup debug logging.
    
    Args:
        enabled: Whether to enable debug logging
        log_file: Optional file path to write logs to
    """
    level = logging.DEBUG if enabled else logging.WARNING
    
    # Clear existing handlers
    logger.handlers.clear()
    logger.setLevel(level)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    
    # Formatter with timestamp
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(file_handler)
    
    if enabled:
        logger.debug("Debug logging enabled")


def log_request(method: str, url: str, headers: dict = None, body: Any = None) -> None:
    """Log an outgoing HTTP request."""
    logger.debug(f">>> {method} {url}")
    if headers:
        # Filter out sensitive headers
        safe_headers = {k: v for k, v in headers.items() if 'auth' not in k.lower()}
        if safe_headers:
            logger.debug(f"    Headers: {safe_headers}")
    if body:
        try:
            body_str = json.dumps(body, indent=2, default=str)
            logger.debug(f"    Body: {body_str}")
        except (TypeError, ValueError):
            logger.debug(f"    Body: {body}")


def log_response(status_code: int, headers: dict = None, body: Any = None, truncate: int = 2000) -> None:
    """Log an incoming HTTP response."""
    logger.debug(f"<<< Response: {status_code}")
    if headers:
        content_type = headers.get('content-type', 'unknown')
        content_length = headers.get('content-length', 'unknown')
        logger.debug(f"    Content-Type: {content_type}, Length: {content_length}")
    if body:
        try:
            if isinstance(body, (dict, list)):
                body_str = json.dumps(body, indent=2, default=str)
            else:
                body_str = str(body)
            
            if len(body_str) > truncate:
                body_str = body_str[:truncate] + f"\n... (truncated, total {len(body_str)} chars)"
            logger.debug(f"    Body: {body_str}")
        except (TypeError, ValueError):
            logger.debug(f"    Body: {body}")


def log_error(message: str, exception: Exception = None) -> None:
    """Log an error."""
    if exception:
        logger.error(f"{message}: {type(exception).__name__}: {exception}")
    else:
        logger.error(message)


def log_info(message: str) -> None:
    """Log info message."""
    logger.info(message)


def log_debug(message: str) -> None:
    """Log debug message."""
    logger.debug(message)


def is_debug_enabled() -> bool:
    """Check if debug logging is enabled."""
    return logger.level <= logging.DEBUG
