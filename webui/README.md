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

[uv](https://docs.astral.sh/uv/) manages the Python environment and dependencies.
The shared dependencies include the browser driver. Fresh WebUI logins also need
Chromium, Xvfb, x11vnc, and noVNC on the host; see the browser login setup below.

## Usage

### Starting the WebUI

Run the dedicated WebUI entry point:

```bash
uv run --group nicegui python main_webui.py
```

See `python main_webui.py --help` for available command-line options (e.g. `--stdlog`, `-v`).

### Accessing the Interface

Once started, open your web browser and navigate to:
- **Default**: `http://localhost:5800` (or `https://localhost:5800` with `SECURE_CONNECTION=1`)
- **Custom**: Set via the `WEBUI_HOST`, `WEBUI_PORT`, and `SECURE_CONNECTION` environment variables

The WebUI listens on localhost by default. For remote access, explicitly set
`WEBUI_HOST` to a network interface, enable `WEBUI_AUTH=1`, and use HTTPS or a trusted
TLS reverse proxy. Dashboard clients can control the embedded login browser.

### Using tkinter Instead

To use the traditional desktop GUI, run the original entry point:

```bash
uv run --group tkinter python main.py
```

### Testing this checkout in Docker

The development image runs `main_webui.py` directly with Python 3.10 on Debian
`bookworm-slim`, with official Google Chrome, Xvfb, x11vnc, and noVNC in the same
container. It runs as root and includes uncommitted changes. Google Chrome's Linux
package requires amd64. This differs from the Alpine/Chromium
[production container](https://github.com/fireph/docker-twitch-drops-miner/blob/main/Dockerfile.webui)
so Chrome login can be tested. Release executables are built separately with
`Dockerfile.build`. Build the development image from the repository root:

```bash
docker build -f Dockerfile.dev -t twitchdropsminer-login-dev .
docker run -d --rm --name twitchdropsminer-login-dev \
  -p 127.0.0.1:5800:5800 --shm-size=1g \
  -e TZ=America/Los_Angeles \
  -v twitchdropsminer-login-dev-config:/app/config \
  twitchdropsminer-login-dev
```

Set `TZ` to your local time zone before running the command. Open
`http://localhost:5800`. Test settings and Twitch login cookies persist in
the named Docker volume. Rebuild the image and restart the container after code
changes. Stop it with `docker stop twitchdropsminer-login-dev`.

With Docker Desktop on Windows, enable **Settings → Resources → WSL Integration**
for your distribution. Alternatively, use `docker.exe` in the commands above.

To run the tests, including the real browser and viewer checks:

```bash
docker run --rm --shm-size=1g -e TDM_BROWSER_TESTS=1 \
  twitchdropsminer-login-dev uv run --no-sync pytest tests/ -q
```

### Building release executables

`Dockerfile.build` supports `LIBC=glibc` (the default, Debian Bookworm) and
`LIBC=musl` (Alpine). CI builds both variants for the `nicegui` and `tkinter`
backends on x86_64 and aarch64. The glibc executable requires glibc 2.36 or newer.

To build and extract the WebUI executable archive for Debian/Ubuntu:

```bash
docker build -f Dockerfile.build --platform linux/amd64 \
  --build-arg LIBC=glibc --build-arg UI_BACKEND=nicegui --build-arg ARCH=x86_64 \
  -t twitchdropsminer-build .
docker create --name twitchdropsminer-extract twitchdropsminer-build
docker cp twitchdropsminer-extract:/app/Twitch.Drops.Miner.Linux.glibc.PyInstaller-nicegui-x86_64.zip .
docker rm twitchdropsminer-extract
```

Select `LIBC=musl` for Alpine; those archives retain their existing
`Twitch.Drops.Miner.Linux.musl.PyInstaller-<backend>-<arch>.zip` names. The new
glibc archives use `glibc` in the same position. Both contain the existing
`Twitch Drops Miner/Twitch Drops Miner (by DevilXD)` executable and `manual.txt`.
Browsers and the WebUI viewer packages remain runtime dependencies.

### Default Chromium/noVNC login (Ubuntu)

WebUI mode opens a real Chromium browser **inside a NiceGUI dialog** by default.
Sign in on Twitch's page and complete its verification prompts there. The browser
uses upstream's Android OAuth login flow. Upstream handles the login URL, captures
the token from Twitch's redirect, validates its client ID, and saves the session.
The WebUI supplies the embedded browser, cancel button, and ten-minute timeout.

Install the virtual display and viewer, then a Chromium browser:

```bash
sudo apt-get install xvfb x11vnc novnc
uvx --from playwright playwright install --with-deps chromium
```

Start from this checkout:

```bash
uv run --group nicegui python main_webui.py
```

Open `http://localhost:5800` and click **Login**. **Close view** hides the dialog
without cancelling; **Show login browser** reopens the same session. **Cancel login**
closes the browser and allows another attempt. The attempt expires after ten minutes.
Passwords and verification codes are entered in Twitch's page. Login requests are
handled by Twitch's page without WebUI interception or rewriting. Upstream's login
messages appear in the dashboard and browser dialog. A successful Android token is
saved through the miner's normal cookie mechanism, and mining resumes automatically.
If upstream asks you to press **Login** again, use the button inside the dialog.

The embedded browser includes the standard noVNC toolbar. Open it using the handle
on the left edge, then select **Clipboard** to paste text from your computer. Click
back into the browser and press **Ctrl+V** to paste it into the selected field. Text
copied inside the browser also appears in the clipboard panel. The toolbar includes
fullscreen, scaling settings, and extra keyboard controls.

The browser has a temporary profile, removed when the attempt ends. The virtual
display and VNC server run only during the attempt. VNC listens on loopback; its
viewer and WebSocket are served through the existing WebUI port, including HTTPS
when configured. An unguessable per-attempt key and a same-origin check restrict
viewer WebSockets. No additional port needs forwarding.

When a reverse proxy terminates HTTPS, TDM can keep serving HTTP internally.
The viewer uses the public page's scheme for its WebSocket connection. Configure
the proxy to preserve the public `Host` header and forward WebSocket upgrades.

Configuration:

- `WEBUI_TWITCH_LOGIN=android-browser` is the default; no environment variable is needed.
- `WEBUI_TWITCH_LOGIN=device-code` selects the legacy device-code flow instead.
- `WEBUI_BROWSER_PATH` selects a Chrome/Chromium executable. Otherwise an installed
  browser is preferred, followed by the latest Playwright cache and Zendriver's discovery.
- `PLAYWRIGHT_BROWSERS_PATH` selects a non-default Playwright browser cache.
- `WEBUI_NOVNC_PATH` overrides `/usr/share/novnc`.

The shared dependencies install Zendriver for both the WebUI and desktop entry points.
Existing valid saved logins are restored normally and skip this flow. Do not delete
working credentials just to test it; use a separate checkout if you need to preserve
an existing session. To select the legacy login explicitly, run:

```bash
WEBUI_TWITCH_LOGIN=device-code uv run --group nicegui python main_webui.py
```

The tkinter entry point uses the same upstream browser login flow in a desktop window.

If a downloaded Chromium cannot start on Ubuntu with a "No usable sandbox" error,
use a browser installed at a path covered by Ubuntu's AppArmor policy and select
it with `WEBUI_BROWSER_PATH`. The WebUI keeps Zendriver's default sandbox
configuration. In the development Docker image, Zendriver disables the browser
sandbox because the container runs as root.

## Configuration

The WebUI host, port, and authentication are configured via environment variables:

- **WEBUI_HOST**: Network interface to bind to (default: `127.0.0.1` with browser login;
  the legacy device-code flow retains `0.0.0.0`)
  - `0.0.0.0` - Listen on all interfaces (accessible from other devices)
  - `127.0.0.1` or `localhost` - Local access only

- **WEBUI_PORT**: Port to serve on, must be an integer between 1 and 65535 (default: `5800`)

- **WEBUI_AUTH**: Enable login authentication (default: `0`)
  - `1` - Require username/password to access the WebUI
  - `0` - No authentication (auth system is completely disabled)

- **SECURE_CONNECTION**: Enable HTTPS (default: `0`)
  - `1` - Serve the WebUI over HTTPS using TLS certificates
  - `0` - Serve the WebUI over plain HTTP

  When `1`, certificates are read from `config/certs/`:
  - `web-privkey.pem` — Web server's private key
  - `web-fullchain.pem` — Web server's certificate, bundled with any root and intermediate certificates

  If either file is missing, a self-signed certificate is automatically generated and written to those paths. Self-signed certs include `localhost` and `127.0.0.1` as Subject Alternative Names, plus the container hostname and its resolved IP when running in Docker with `--hostname`. Auto-generation requires `openssl` to be installed.

```bash
WEBUI_HOST=127.0.0.1 WEBUI_PORT=8080 WEBUI_AUTH=1 SECURE_CONNECTION=1 uv run --group nicegui python main_webui.py
```

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

- Browser login defaults to localhost (`127.0.0.1`); set `WEBUI_HOST` explicitly for remote access
- Consider firewall rules or a reverse proxy if exposing beyond your local network

### Authentication

When enabled, the WebUI requires a login before accessing the dashboard:

- **First visit** (no users exist): You'll be prompted to register an admin account with a username, password, and confirmation
- **Subsequent visits**: Sign in with the registered username and password
- Credentials are stored hashed (argon2) in `config/webui_auth.db`
- A random JWT signing secret is auto-generated and stored in the same database
- Login attempts are rate-limited to 5 per minute per IP address
- A logout button appears in the header bar when auth is enabled
- Sessions last 30 days via an httponly cookie

Authentication is disabled by default (`WEBUI_AUTH=0`). The entire auth system is skipped — no middleware, no login page, no database is created.

## Troubleshooting

**"NiceGUI is not installed" error**

Ensure you synced the nicegui group:
```bash
uv sync --group nicegui
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
