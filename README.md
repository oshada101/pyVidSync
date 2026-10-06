# Python Video Player with PartyKit Sync

A synchronized video player. All participants run the same Python app — host controls playback, viewers follow.

## Features

- Play video files (MP4, MKV, AVI, MOV, WebM)
- Real-time sync across all participants, with clock-offset compensation and drift correction
- Host/viewer roles with room codes
- Host transfer (⚙ → Transfer host to) and automatic host reclaim after a reconnect

## Project Structure

```
pyVidSync/
├── main.py                # Role-select dialog + SyncApp (sync logic, runs on the Qt thread)
├── video_player.py        # VLC-based video player window (PyQt6)
├── partysocket_client.py  # WebSocket client for PartyKit (own asyncio thread)
├── sync_logic.py          # Pure helpers: room codes, URL building, sync math, clock sync
├── settings.py            # Settings load/save
├── relay_server.py        # Relay server for your own VPS (single file, needs only websockets)
├── deploy/                # systemd unit + optional Caddyfile for the VPS
├── tests/                 # pytest suite
├── party/
│   ├── server.ts          # Same server for PartyKit (one instance per room)
│   └── server.test.ts     # vitest suite
└── partykit.json          # PartyKit configuration
```

## Setup

Requires a system VLC install (libvlc) and Python 3.10+.

```bash
uv venv .venv
uv pip install --python .venv -r requirements.txt -r requirements-dev.txt
npm install
```

## Quick Start (Local)

```bash
.venv/bin/python relay_server.py     # relay on localhost:1999 (or: npm run dev for PartyKit)
PARTYKIT_HOST=localhost:1999 .venv/bin/python main.py
```

Or set the host in the app: launch → ⚙ Settings → PartyKit Host → Save.

## Tests

```bash
.venv/bin/python -m pytest           # client + relay server (stubs libvlc, no VLC install needed)
npm test && npm run typecheck        # server
```

## Deploy to a VPS (recommended)

`relay_server.py` speaks the same protocol as the PartyKit server. It's a single file with one dependency and uses about 30 MB of RAM.

On the VPS (Debian/Ubuntu), one-time setup:

```bash
sudo apt update && sudo apt install -y git python3-venv
sudo git clone https://github.com/oshada101/pyVidSync.git /opt/videosync
sudo python3 -m venv /opt/videosync/venv
sudo /opt/videosync/venv/bin/pip install 'websockets>=14'
sudo cp /opt/videosync/deploy/videosync-*.service /opt/videosync/deploy/videosync-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now videosync-relay videosync-update.timer
```

Then choose how clients reach it:

- **With a domain (wss, recommended):** install Caddy, use `deploy/Caddyfile` with your domain, and open ports 80 and 443 (`sudo ufw allow 80,443/tcp`). Clients use the host `sync.yourdomain.com`.
- **Without a domain (plain ws):** expose the port with a drop-in, which survives auto-updates, and open the port:
  ```bash
  sudo mkdir -p /etc/systemd/system/videosync-relay.service.d
  printf '[Service]\nEnvironment=HOST=0.0.0.0\n' | sudo tee /etc/systemd/system/videosync-relay.service.d/override.conf
  sudo systemctl daemon-reload && sudo systemctl restart videosync-relay
  sudo ufw allow 1999/tcp
  ```
  Clients use the host `ws://<vps-ip>:1999`. Traffic is unencrypted, so room codes and host tokens are visible on the network path.

Check it from your computer: `curl http://<vps-ip>:1999/` should print `videosync ok`.

### Auto-deploy

`videosync-update.timer` runs `deploy/auto-update.sh` every minute. The script pulls `main`, and if `relay_server.py` or the service file changed, it restarts the relay. A restart briefly disconnects clients; they reconnect on their own and the host gets its role back. Commits that only touch the desktop app never restart the server. The repo is public, so no deploy keys or GitHub secrets are needed.

- Update logs: `journalctl -u videosync-update -f`
- Relay logs: `journalctl -u videosync-relay -f`
- Next check: `systemctl list-timers videosync-update.timer`

## Deploy to PartyKit (managed)

```bash
npm run deploy
```

Note the host from the output (e.g. `yourapp.partykit.dev`) and configure it. As of October 2026, new deploys can fail with "exceeded the limit of 10000 Workers custom domains on zone 'partykit.dev'". That limit is on PartyKit's side; use the VPS option instead.

## Configuring the Host

Resolution order (first match wins):

1. `PARTYKIT_HOST` environment variable (also read from `.env` when running from source)
2. User settings file, written by the in-app Settings panel:
   - macOS: `~/Library/Application Support/VideoSync/settings.json`
   - Windows: `%APPDATA%\VideoSync\settings.json`
   - Linux: `$XDG_CONFIG_HOME/VideoSync/settings.json` (default `~/.config/VideoSync/`)
3. `settings.json` next to the executable (frozen app) or `main.py` (source). Read-only; use it to ship a default:
   ```json
   { "partykit_host": "yourapp.partykit.dev" }
   ```

Accepted host values: `yourapp.partykit.dev` (wss), `localhost:1999` (ws), or an explicit URL such as `ws://192.168.1.5:1999` for a LAN dev server.

## How It Works

1. Host generates a room code (e.g. `ABCD-1234`) and shares it out-of-band.
2. Viewers enter the code. Joining a room that has no host shows "Room not found" and retries until the host connects.
3. Each participant opens their own local copy of the video.
4. Host controls playback; the server relays sync messages to viewers.

### Roles

- The host connects with `?role=host&token=<per-session secret>`. The token is never sent to other clients.
- If the host drops, the earliest-joined viewer is promoted. When the original host reconnects with the same token, the server gives the role back.
- The server only relays `sync`/`heartbeat` messages from the current host, and rebuilds each one from validated fields. Any other client message is dropped.

### Sync messages (host → viewers)

```json
{ "type": "sync", "state": "playing", "videoTime": 12.5, "wallClock": 1234567890.0, "filename": "movie.mp4", "senderId": "..." }
```

`wallClock` is in **server time**. Each client estimates its offset to the server clock with `ping`/`pong`, keeping the lowest-RTT sample. This keeps viewers in sync even when the machines' clocks disagree.

- `sync` is sent on play/pause/seek (debounced 120 ms) and when a viewer joins; viewers always apply it.
- `heartbeat` carries the same fields every second. Viewers re-seek only when they drift more than 0.75 s.
- A viewer shows a warning and pauses after 3 s without a heartbeat.

## Building

**Linux** (from any machine with Docker, including macOS):

```bash
docker build --platform linux/amd64 -f packaging/linux.Dockerfile --output dist-linux .
```

This produces `dist-linux/videosync-linux-x86_64.tar.gz`. The build doesn't bundle VLC, so the target machine needs it installed:

```bash
sudo apt install vlc            # Debian/Ubuntu; use your distro's package elsewhere
tar xzf videosync-linux-x86_64.tar.gz
./videosync/videosync
```

The build targets glibc 2.35, so it runs on Ubuntu 22.04+, Debian 12+ and similar. The app forces X11 (`QT_QPA_PLATFORM=xcb`) so VLC can embed into the window, which on Wayland runs through XWayland.

**Windows** (on Windows with VLC installed; set `VLC_DIR` if VLC isn't in Program Files):

```bash
pyinstaller videosync-windows.spec
```
