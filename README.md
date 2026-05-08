# Python Video Player with PartyKit Sync

A synchronized video player. All participants run the same Python app — host controls playback, viewers follow.

## Features

- Play video files (MP4, MKV, AVI, MOV, WebM)
- Real-time sync across all participants
- Host/viewer roles with room codes
- Host transfer support

## Project Structure

```
python-player/
├── main.py                # Main app + UI (role select, sync logic)
├── video_player.py        # VLC-based video player (PyQt6)
├── partysocket_client.py  # WebSocket client for PartyKit
├── settings.py            # Settings load/save (settings.json)
├── requirements.txt       # Python dependencies
├── party/
│   └── server.ts          # PartyKit server
├── public/
│   └── index.html         # Web viewer UI
└── partykit.json          # PartyKit configuration
```

## Quick Start (Local)

### 1. Start PartyKit Server

```bash
npx partykit dev --port 1999
```

### 2. Configure Host

Set `PARTYKIT_HOST` in `.env`:

```
PARTYKIT_HOST=localhost:1999
```

Or set it in the app UI: launch `main.py` → Settings → PartyKit Host.

### 3. Run

```bash
python3 main.py
```

## Deploy to Cloud

### 1. Deploy PartyKit Server

```bash
npx partykit deploy
```

Note the host from the output (e.g. `yourapp.partykit.dev`).

### 2. Configure the Host

**Via `.env`** (dev):
```
PARTYKIT_HOST=yourapp.partykit.dev
```

**Via UI** (dev or frozen app): launch → Settings → PartyKit Host → Save.

**Via `settings.json`** next to the executable (frozen app):
```json
{ "partykit_host": "yourapp.partykit.dev" }
```

**Via environment variable** (any mode):
```bash
PARTYKIT_HOST=yourapp.partykit.dev python3 main.py
```

Priority: env var → `settings.json` → UI-saved setting.

## How It Works

1. Host generates a room code and shares it out-of-band.
2. Viewers enter the code to join the room.
3. Host controls playback; sync messages broadcast to all viewers via PartyKit.
4. Each participant has a local copy of the video file.

### Sync messages (host → viewers)

```json
{ "type": "sync", "state": "playing", "videoTime": 12.5, "wallClock": 1234567890.0 }
```

Viewer compensates for latency using `wallClock` delta before seeking.

### Heartbeat

Host sends a heartbeat every 1s. Viewers show a warning after 3s silence. Earliest-joined viewer auto-promotes to host on disconnect.

## Dependencies

```bash
pip install PyQt6 python-vlc websockets python-dotenv
```
