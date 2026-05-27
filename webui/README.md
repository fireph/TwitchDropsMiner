# Web UI for Twitch Drops Miner

The Twitch Drops Miner includes a modern web-based interface using [NiceGUI](https://nicegui.io/). Access your mining dashboard from any device on your network through a web browser - no desktop environment required.

## How It Works

The WebUI runs entirely within a single asyncio event loop alongside the Twitch backend. This single-threaded architecture eliminates thread synchronization issues and provides better performance and reliability compared to the previous threading-based implementation.

When you start the WebUI:
1. The NiceGUI server starts and serves the web interface
2. The Twitch backend runs within the same event loop
3. You access the dashboard through any web browser
4. Multiple browser tabs can connect simultaneously with full state synchronization

## Installation

The WebUI requires the NiceGUI dependencies:

```bash
pip install -r requirements-nicegui.txt
```

## Usage

### Starting the WebUI

Run the dedicated WebUI entry point:

```bash
python main_webui.py
```

See `python main_webui.py --help` for available command-line options (e.g. `--stdlog`, `-v`).

### Accessing the Interface

Once started, open your web browser and navigate to:
- **Default**: `http://localhost:5800`
- **Custom**: Set via the `WEBUI_HOST` and `WEBUI_PORT` environment variables

The WebUI is accessible from any device on your network. Use your machine's IP address to access remotely (e.g., `http://192.168.1.100:5800`).

### Using tkinter Instead

To use the traditional desktop GUI, run the original entry point:

```bash
python main.py
```

## Configuration

The WebUI is configured via environment variables:

- **WEBUI_HOST**: Network interface to bind to (default: `0.0.0.0`)
  - `0.0.0.0` - Listen on all interfaces (accessible from other devices)
  - `127.0.0.1` or `localhost` - Local access only

- **WEBUI_PORT**: Port to serve on, must be an integer between 1 and 65535 (default: `5800`)

- **WEBUI_AUTH**: Toggle the WebUI login wall (default: `on`)
  - `on` (default) — requires sign-in; on first launch you're redirected to `/setup` to create a username and password, stored hashed in `config/webui_auth.json`
  - `off`, `0`, `false`, `no` — disables the login wall entirely (only safe on a trusted LAN)

```bash
WEBUI_HOST=127.0.0.1 WEBUI_PORT=8080 python main_webui.py
```

For Docker, pass it as an env: `docker run -e WEBUI_AUTH=off ...`

## Features

The WebUI provides all the functionality of the traditional GUI:

- **Main Tab**: Real-time console output, status monitoring, progress tracking, and channel management
- **Inventory Tab**: View available drops and campaigns  
- **Settings Tab**: Configure games, priorities, and WebUI settings
- **Help Tab**: Application information and links

## Comparison with tkinter GUI

| Feature | WebUI | tkinter GUI |
|---------|-------|-------------|
| Access | Any browser on network | Desktop only |
| Multiple views | Multiple browser tabs | Single window |
| Remote access | Yes | No |
| System tray | Not available | Supported |
| Architecture | Single event loop | Separate threads |

## Security Notes

- By default, the WebUI listens on all interfaces (`0.0.0.0`), making it accessible from other devices
- Set `WEBUI_HOST=127.0.0.1` for local-only access
- A username/password login wall is enabled by default — set `WEBUI_AUTH=off` to disable when running on a trusted LAN
- Credentials are stored hashed (PBKDF2-SHA256, 200 000 iterations) in `config/webui_auth.json` together with the session-cookie secret; delete the file to reset
- The `/login` endpoint enforces per-IP exponential backoff after 5 failed attempts (up to 15 min) to slow down online brute-force
- **Exposing the WebUI to the public internet still requires HTTPS** — put it behind a reverse proxy (nginx, Caddy, Cloudflare Tunnel, Traefik) with TLS. Without HTTPS, the password and session cookie travel in plaintext and can be sniffed
- Strong, unique passwords matter — PBKDF2 only slows guessing, it doesn't compensate for weak passwords

## Troubleshooting

**"NiceGUI is not installed" error**
```bash
pip install nicegui
```

**Cannot access from another device**
- Check that `WEBUI_HOST` is set to `0.0.0.0`
- Verify firewall rules allow connections on the configured port
- Use the host machine's IP address, not `localhost`

**Port already in use**
- Change `WEBUI_PORT` to a different value (e.g., `8081` or `9000`)
- Find what's using the port: `lsof -i :5800` (Linux/Mac) or `netstat -ano | findstr :5800` (Windows)

## Technical Note

The WebUI implementation uses a single-threaded architecture where the NiceGUI server and Twitch backend share the same asyncio event loop. This eliminates the need for thread synchronization utilities and provides better performance.
