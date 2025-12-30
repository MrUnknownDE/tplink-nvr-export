"""Command-line interface for TP-Link Vigi NVR Export."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .auth import AuthenticationError
from .debug import setup_debug_logging
from .nvr_client import NVRAPIError, NVRClient


def parse_datetime(value: str) -> datetime:
    """Parse datetime from various formats."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    
    raise click.BadParameter(
        f"Invalid datetime format: {value}. "
        f"Use 'YYYY-MM-DD HH:MM' or 'DD.MM.YYYY HH:MM'"
    )


class DateTimeParamType(click.ParamType):
    """Click parameter type for datetime values."""
    
    name = "datetime"
    
    def convert(self, value, param, ctx):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return parse_datetime(value)
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


DATETIME = DateTimeParamType()


@click.group()
@click.version_option(version=__version__, prog_name="nvr-export")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging (shows all API requests/responses)")
@click.option("--debug-file", type=click.Path(), help="Write debug log to file")
@click.pass_context
def main(ctx, debug: bool, debug_file: str):
    """TP-Link Vigi NVR Export Tool.
    
    Export video recordings from TP-Link Vigi NVRs via OpenAPI.
    
    Make sure OpenAPI is enabled on your NVR:
    Settings > Network > OpenAPI (default port: 20443)
    
    \b
    Debug mode:
        nvr-export --debug export ...
        nvr-export --debug --debug-file debug.log export ...
    """
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug
    
    # Setup debug logging
    setup_debug_logging(enabled=debug, log_file=debug_file)
    
    if debug:
        click.echo("🔧 Debug mode enabled - all API requests will be logged", err=True)


@main.command()
@click.option("--host", "-h", required=True, help="NVR IP address or hostname")
@click.option("--port", "-p", default=20443, help="OpenAPI port (default: 20443)")
@click.option("--user", "-u", required=True, help="Admin username")
@click.option("--password", "-P", required=True, prompt=True, hide_input=True, help="Admin password")
@click.option("--channel", "-c", required=True, type=int, help="Camera channel ID (1-based)")
@click.option("--start", "-s", required=True, type=DATETIME, help="Start time (YYYY-MM-DD HH:MM)")
@click.option("--end", "-e", required=True, type=DATETIME, help="End time (YYYY-MM-DD HH:MM)")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output directory")
@click.option("--type", "rec_type", default="all", 
              type=click.Choice(["all", "continuous", "motion", "alarm"]),
              help="Recording type filter")
@click.option("--no-ssl-verify", is_flag=True, default=True, help="Skip SSL certificate verification")
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output")
@click.pass_context
def export(
    ctx,
    host: str,
    port: int,
    user: str,
    password: str,
    channel: int,
    start: datetime,
    end: datetime,
    output: str,
    rec_type: str,
    no_ssl_verify: bool,
    quiet: bool,
):
    """Export recordings from NVR for a time range.
    
    \b
    Examples:
        # Export channel 1 for a specific day
        nvr-export export -h 192.168.1.100 -u admin -c 1 \\
            -s "2024-12-28 00:00" -e "2024-12-28 23:59" -o ./exports
        
        # Export with debug logging
        nvr-export --debug export -h 192.168.1.100 -u admin -c 1 \\
            -s "2024-12-28" -e "2024-12-29" -o ./exports
    """
    output_dir = Path(output)
    
    if not quiet:
        click.echo(f"Connecting to NVR at {host}:{port}...")
    
    try:
        with NVRClient(host, user, password, port, verify_ssl=not no_ssl_verify) as client:
            if not quiet:
                click.echo(f"Searching recordings: Channel {channel}, {start} to {end}")
            
            recordings = client.search_recordings(channel, start, end, rec_type)
            
            if not recordings:
                click.echo("No recordings found for the specified time range.")
                if ctx.obj.get('debug'):
                    click.echo("💡 Tip: Check debug output above for API responses", err=True)
                return
            
            # Calculate total size
            total_size_mb = sum(r.size_bytes for r in recordings) / (1024 * 1024)
            
            if not quiet:
                click.echo(f"Found {len(recordings)} recordings ({total_size_mb:.1f} MB total)")
            
            # Download recordings
            downloaded = client.export_time_range(
                channel, start, end, output_dir, rec_type, show_progress=not quiet
            )
            
            if not quiet:
                click.echo(f"\nSuccessfully exported {len(downloaded)} recordings to {output_dir}")
                
    except AuthenticationError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        sys.exit(1)
    except NVRAPIError as e:
        click.echo(f"NVR API error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        if ctx.obj.get('debug'):
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@main.command()
@click.option("--host", "-h", required=True, help="NVR IP address or hostname")
@click.option("--port", "-p", default=20443, help="OpenAPI port (default: 20443)")
@click.option("--user", "-u", required=True, help="Admin username")
@click.option("--password", "-P", required=True, prompt=True, hide_input=True, help="Admin password")
@click.option("--no-ssl-verify", is_flag=True, default=True, help="Skip SSL certificate verification")
@click.pass_context
def channels(
    ctx,
    host: str,
    port: int,
    user: str,
    password: str,
    no_ssl_verify: bool,
):
    """List available camera channels on NVR."""
    try:
        with NVRClient(host, user, password, port, verify_ssl=not no_ssl_verify) as client:
            click.echo(f"Connecting to NVR at {host}:{port}...")
            channel_list = client.get_channels()
            
            if not channel_list:
                click.echo("No channels found.")
                return
            
            click.echo(f"\nFound {len(channel_list)} channels:")
            click.echo("-" * 40)
            
            for ch in channel_list:
                status = "✓" if ch.enabled else "✗"
                click.echo(f"  [{status}] Channel {ch.id}: {ch.name}")
                
    except AuthenticationError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        sys.exit(1)
    except NVRAPIError as e:
        click.echo(f"NVR API error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--host", "-h", required=True, help="NVR IP address or hostname")
@click.option("--port", "-p", default=20443, help="OpenAPI port (default: 20443)")
@click.option("--user", "-u", required=True, help="Admin username")
@click.option("--password", "-P", required=True, prompt=True, hide_input=True, help="Admin password")
@click.option("--channel", "-c", required=True, type=int, help="Camera channel ID")
@click.option("--start", "-s", required=True, type=DATETIME, help="Start time")
@click.option("--end", "-e", required=True, type=DATETIME, help="End time")
@click.option("--type", "rec_type", default="all",
              type=click.Choice(["all", "continuous", "motion", "alarm"]))
@click.option("--no-ssl-verify", is_flag=True, default=True)
@click.pass_context
def search(
    ctx,
    host: str,
    port: int,
    user: str,
    password: str,
    channel: int,
    start: datetime,
    end: datetime,
    rec_type: str,
    no_ssl_verify: bool,
):
    """Search for recordings without downloading."""
    try:
        with NVRClient(host, user, password, port, verify_ssl=not no_ssl_verify) as client:
            recordings = client.search_recordings(channel, start, end, rec_type)
            
            if not recordings:
                click.echo("No recordings found.")
                if ctx.obj.get('debug'):
                    click.echo("💡 Tip: Check debug output above for API responses", err=True)
                return
            
            total_size = sum(r.size_bytes for r in recordings) / (1024 * 1024)
            total_duration = sum(r.duration_seconds for r in recordings)
            
            click.echo(f"\nFound {len(recordings)} recordings:")
            click.echo(f"Total size: {total_size:.1f} MB")
            click.echo(f"Total duration: {total_duration // 3600}h {(total_duration % 3600) // 60}m")
            click.echo("-" * 60)
            
            for rec in recordings:
                click.echo(
                    f"  {rec.start_time:%Y-%m-%d %H:%M} - {rec.end_time:%H:%M} "
                    f"({rec.size_mb:.1f} MB, {rec.recording_type})"
                )
                
    except AuthenticationError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        sys.exit(1)
    except NVRAPIError as e:
        click.echo(f"NVR API error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--host", "-h", required=True, help="NVR IP address or hostname")
@click.option("--port", "-p", default=20443, help="OpenAPI port (default: 20443)")
@click.option("--user", "-u", required=True, help="Admin username")
@click.option("--password", "-P", required=True, prompt=True, hide_input=True, help="Admin password")
@click.option("--no-ssl-verify", is_flag=True, default=True)
@click.pass_context
def discover(
    ctx,
    host: str,
    port: int,
    user: str,
    password: str,
    no_ssl_verify: bool,
):
    """Discover available API endpoints on the NVR.
    
    This command probes many possible API paths to find which ones
    are available on your NVR. Useful for debugging and development.
    """
    import requests
    
    # Common endpoints to try
    endpoints_to_probe = [
        # Root and info
        ("GET", "/openapi"),
        ("GET", "/openapi/"),
        ("GET", "/openapi/info"),
        ("GET", "/openapi/version"),
        ("GET", "/openapi/api"),
        ("GET", "/openapi/swagger"),
        ("GET", "/openapi/docs"),
        
        # Device/channels
        ("GET", "/openapi/device"),
        ("GET", "/openapi/devices"),
        ("GET", "/openapi/added_devices"),
        ("GET", "/openapi/channel"),
        ("GET", "/openapi/channels"),
        ("GET", "/openapi/channelList"),
        ("GET", "/openapi/device/info"),
        ("GET", "/openapi/device/list"),
        ("GET", "/openapi/device/channels"),
        ("GET", "/openapi/nvr/info"),
        ("GET", "/openapi/nvr/channels"),
        
        # Recording/playback
        ("GET", "/openapi/record"),
        ("GET", "/openapi/records"),
        ("GET", "/openapi/recording"),
        ("GET", "/openapi/recordings"),
        ("GET", "/openapi/playback"),
        ("GET", "/openapi/video"),
        ("GET", "/openapi/videos"),
        ("GET", "/openapi/storage"),
        ("GET", "/openapi/storage/recordings"),
        ("GET", "/openapi/hdd"),
        ("GET", "/openapi/disk"),
        
        # Search endpoints
        ("GET", "/openapi/search"),
        ("GET", "/openapi/record/list"),
        ("GET", "/openapi/recording/list"),
        ("GET", "/openapi/playback/list"),
        ("GET", "/openapi/video/list"),
        
        # Live stream
        ("GET", "/openapi/live"),
        ("GET", "/openapi/stream"),
        ("GET", "/openapi/liveStream"),
        ("GET", "/openapi/rtsp"),
        
        # Events
        ("GET", "/openapi/event"),
        ("GET", "/openapi/events"),
        ("GET", "/openapi/event/list"),
        ("GET", "/openapi/alarm"),
        ("GET", "/openapi/alarms"),
        
        # Settings
        ("GET", "/openapi/settings"),
        ("GET", "/openapi/config"),
        ("GET", "/openapi/system"),
        ("GET", "/openapi/sound"),
        ("GET", "/openapi/network"),
        
        # User
        ("GET", "/openapi/user"),
        ("GET", "/openapi/users"),
        ("GET", "/openapi/account"),
    ]
    
    click.echo(f"Connecting to NVR at {host}:{port}...")
    
    try:
        from .auth import NVRAuthenticator
        
        auth = NVRAuthenticator(host, user, password, port, verify_ssl=not no_ssl_verify)
        session = auth.get_authenticated_session()
        base_url = f"https://{host}:{port}"
        
        click.echo(f"Authentication successful!")
        click.echo(f"\nProbing {len(endpoints_to_probe)} endpoints...\n")
        
        found_endpoints = []
        
        for method, endpoint in endpoints_to_probe:
            url = f"{base_url}{endpoint}"
            try:
                if method == "GET":
                    response = session.get(url, timeout=5)
                else:
                    response = session.post(url, json={}, timeout=5)
                
                status = response.status_code
                
                if status == 200:
                    # Try to get response preview
                    try:
                        data = response.json()
                        preview = str(data)[:100]
                    except:
                        preview = response.text[:100] if response.text else "(empty)"
                    
                    click.echo(f"✅ {status} {method:4} {endpoint}")
                    click.echo(f"   Response: {preview}...")
                    found_endpoints.append((method, endpoint, status))
                elif status in (400, 401, 403, 405):
                    # Exists but needs different params/auth
                    click.echo(f"⚠️  {status} {method:4} {endpoint} (exists but access denied/bad request)")
                    found_endpoints.append((method, endpoint, status))
                # 404 = not found, skip silently
                    
            except requests.RequestException as e:
                pass  # Skip connection errors
        
        click.echo(f"\n{'='*60}")
        click.echo(f"Summary: Found {len(found_endpoints)} accessible endpoints")
        
        if found_endpoints:
            click.echo("\nWorking endpoints (200 OK):")
            for method, endpoint, status in found_endpoints:
                if status == 200:
                    click.echo(f"  {method} {endpoint}")
            
            click.echo("\nEndpoints that exist but need work:")
            for method, endpoint, status in found_endpoints:
                if status != 200:
                    click.echo(f"  {method} {endpoint} ({status})")
        else:
            click.echo("\n⚠️  No working endpoints found!")
            click.echo("The NVR might use a different API structure.")
            click.echo("Try checking the NVR web interface with browser DevTools.")
                
    except AuthenticationError as e:
        click.echo(f"Authentication failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
