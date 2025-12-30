"""Command-line interface for TP-Link Vigi NVR Export."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .auth import AuthenticationError
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
def main():
    """TP-Link Vigi NVR Export Tool.
    
    Export video recordings from TP-Link Vigi NVRs via OpenAPI.
    
    Make sure OpenAPI is enabled on your NVR:
    Settings > Network > OpenAPI (default port: 20443)
    """
    pass


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
def export(
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
        
        # Export only motion recordings
        nvr-export export -h 192.168.1.100 -u admin -c 2 \\
            -s "2024-12-01" -e "2024-12-31" --type motion -o ./exports
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
        sys.exit(1)


@main.command()
@click.option("--host", "-h", required=True, help="NVR IP address or hostname")
@click.option("--port", "-p", default=20443, help="OpenAPI port (default: 20443)")
@click.option("--user", "-u", required=True, help="Admin username")
@click.option("--password", "-P", required=True, prompt=True, hide_input=True, help="Admin password")
@click.option("--no-ssl-verify", is_flag=True, default=True, help="Skip SSL certificate verification")
def channels(
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
def search(
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


if __name__ == "__main__":
    main()
