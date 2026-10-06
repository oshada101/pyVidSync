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
├── tests/                 # pytest suite
├── party/
│   ├── server.ts          # PartyKit server (one instance per room)
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
npm run dev                          # PartyKit server on localhost:1999
PARTYKIT_HOST=localhost:1999 .venv/bin/python main.py
```

Or set the host in the app: launch → ⚙ Settings → PartyKit Host → Save.

## Tests

```bash
.venv/bin/python -m pytest           # Python (stubs libvlc, no VLC install needed)
npm test && npm run typecheck        # server
```

## Deploy to Cloud

```bash
npm run deploy
```

Note the host from the output (e.g. `yourapp.partykit.dev`) and configure it.

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

```bash
pyinstaller videosync.spec            # Linux (override VLC_LIB_DIR / VLC_PLUGINS_DIR if needed)
pyinstaller videosync-windows.spec    # Windows (override VLC_DIR if VLC isn't in Program Files)
```
