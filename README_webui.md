# Web UI for Twitch Drops Miner

This project now supports both the traditional tkinter GUI and a new web-based interface using NiceGUI.

## Installation

To use the web UI, install NiceGUI:

```bash
pip install nicegui
```

## Usage

### Using Web UI

Set the `UI_BACKEND` environment variable to choose your interface:

```bash
# Windows
set UI_BACKEND=nicegui
python main.py

# Linux/Mac
UI_BACKEND=nicegui python main.py
```

### Configuration

You can configure the UI using environment variables:

- `UI_BACKEND`: Set to "nicegui" for web UI or "tkinter" for desktop GUI (default: tkinter)
- `WEBUI_HOST`: Host for web UI (default: 127.0.0.1)
- `WEBUI_PORT`: Port for web UI (default: 8080)

### Examples

```bash
# Use web UI on default host and port
UI_BACKEND=nicegui python main.py

# Use web UI on custom host and port
UI_BACKEND=nicegui WEBUI_HOST=0.0.0.0 WEBUI_PORT=9000 python main.py

# Use traditional tkinter GUI (default)
UI_BACKEND=tkinter python main.py

# Use traditional tkinter GUI (default - no environment variable needed)
python main.py
```

## Features

The web UI provides the same functionality as the tkinter GUI:

- Real-time console output
- Status monitoring
- Progress tracking
- Channel management
- Stop/start controls

## Browser Access

When using the web UI, open your browser and navigate to:
- Default: http://127.0.0.1:8080
- Custom: http://[WEBUI_HOST]:[WEBUI_PORT]

## Fallback

If NiceGUI is not installed or there's an error loading the web UI, the application will automatically fall back to the traditional tkinter GUI.