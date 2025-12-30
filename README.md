# TP-Link Vigi NVR Export

A CLI tool to export video recordings from TP-Link Vigi NVRs over a specified time period.

> ⚠️ **Note**: This tool is in early development. API endpoints may need adjustment based on your specific NVR model and firmware version.

## Features

- 📹 Export recordings by time range
- 📅 Filter by date/time with flexible formats
- 🎯 Filter by recording type (continuous, motion, alarm)
- 📊 Progress bar during downloads
- 🔒 Secure authentication via OpenAPI

## Requirements

- Python 3.10+
- TP-Link Vigi NVR with OpenAPI enabled
- Network access to NVR on port 20443 (default)

## Installation

### Option 1: Download Windows Executable (Recommended for Windows)

1. Go to [Releases](https://github.com/johannes/tplink-nvr-export/releases)
2. Download `nvr-export-windows.exe`
3. Run from Command Prompt or PowerShell

```powershell
# Example usage
.\nvr-export-windows.exe export -h 192.168.1.100 -u admin -c 1 -s "2024-12-28" -e "2024-12-29" -o ./exports
```

### Option 2: Install with pip (Requires Python)

```bash
# Clone the repository
git clone https://github.com/johannes/tplink-nvr-export.git
cd tplink-nvr-export

# Install with pip
pip install -e .

# Or with pipx for isolated environment
pipx install .
```

### Option 3: Build Windows Executable Locally

```bash
# Install dependencies
pip install -e ".[dev]"

# Build single-file executable
pyinstaller --onefile --name nvr-export --console src/tplink_nvr_export/cli.py

# Executable will be in dist/nvr-export.exe
```

## NVR Setup

Before using this tool, enable OpenAPI on your NVR:

1. Open NVR web interface (https://your-nvr-ip)
2. Navigate to **Settings > Network > OpenAPI**
3. Enable OpenAPI
4. Note the port (default: 20443)

## Usage

### Export recordings

```bash
# Export recordings from channel 1 for a specific day
nvr-export export \
    --host 192.168.1.100 \
    --user admin \
    --channel 1 \
    --start "2024-12-28 00:00" \
    --end "2024-12-28 23:59" \
    --output ./exports

# Export only motion recordings
nvr-export export \
    --host 192.168.1.100 \
    --user admin \
    --channel 2 \
    --start "2024-12-01" \
    --end "2024-12-31" \
    --type motion \
    --output ./exports
```

### List channels

```bash
nvr-export channels --host 192.168.1.100 --user admin
```

### Search recordings (without downloading)

```bash
nvr-export search \
    --host 192.168.1.100 \
    --user admin \
    --channel 1 \
    --start "2024-12-28" \
    --end "2024-12-29"
```

## Supported Time Formats

- `YYYY-MM-DD HH:MM:SS`
- `YYYY-MM-DD HH:MM`
- `YYYY-MM-DD`
- `DD.MM.YYYY HH:MM:SS`
- `DD.MM.YYYY HH:MM`
- `DD.MM.YYYY`

## Tested NVR Models

- VIGI NVR4032H (Firmware 1.4.0)

Should work with other VIGI NVR models supporting OpenAPI:
- VIGI NVR1008H
- VIGI NVR1016H
- VIGI NVR2016H
- VIGI NVR4016H

## Troubleshooting

### Connection refused
- Ensure OpenAPI is enabled on the NVR
- Check firewall allows port 20443
- Verify NVR IP address

### Authentication failed
- Verify username and password
- Ensure user has admin privileges

### No recordings found
- Check the channel ID exists (use `channels` command)
- Verify recordings exist for the time range
- Try with `--type all`

## License

MIT License

## Contributing

Contributions welcome! Please open an issue first to discuss changes.
