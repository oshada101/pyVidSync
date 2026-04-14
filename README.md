# Python Video Player with PartyKit Sync

A Python video player with real-time sync to browsers via PartyKit WebSocket server.

## Features

- Play video files (MP4, MKV, AVI, MOV, WebM)
- Audio playback via pygame
- Real-time sync with connected browsers
- Send play/pause/seek commands from browser to Python
- Cloud deployment for remote connections

## Project Structure

```
python-player/
├── main.py              # Main app (video player + PartyKit client)
├── video_player.py      # OpenCV-based video player with pygame audio
├── partysocket_client.py # WebSocket client for PartyKit
├── requirements.txt     # Python dependencies
├── party/
│   └── server.ts        # PartyKit server (broadcasts messages)
├── public/
│   └── index.html       # Web viewer UI
└── partykit.json        # PartyKit configuration
```

## Quick Start (Local)

### 1. Start PartyKit Server

```bash
cd python-player
npx partykit dev --port 1999
```

### 2. Run Python Video Player

```bash
cd python-player
python3 main.py
```

### 3. Test Locally

Open browser to: http://localhost:1999

## Deploy to Cloud

### 1. Deploy PartyKit Server

```bash
cd python-player
npx partykit deploy
```

This gives you a URL like: `https://python-sync-server.eastcoast.partykit.dev`

### 2. Update Python Client (if needed)

The client is already configured to use the cloud URL:
- Default: `python-sync-server.eastcoast.partykit.dev`
- Override with environment variable: `PARTYKIT_HOST=your-host.partykit.dev`

### 3. Run Python

```bash
python3 main.py
```

### 4. Share with Others

Send them the URL: `https://python-sync-server.eastcoast.partykit.dev`

They can view the sync status and send play/pause/seek commands back to control your video.

## How It Works

1. **Python** runs as the video host, connects to PartyKit WebSocket
2. **PartyKit** broadcasts messages to all connected browsers
3. **Browser** receives sync messages (videoTime, state, duration)
4. **Browser** can send commands back (play, pause, seek)

### Message Format

**From Python (sync state):**
```json
{
  "type": "sync",
  "videoTime": 12.5,
  "duration": 120.0,
  "state": "playing",
  "timestamp": 1776122400.0
}
```

**From Browser (commands):**
```json
{"type": "play"}
{"type": "pause"}
{"type": "seek", "timestamp": 10}
```

## Dependencies

- Python 3.10+
- PyQt6 (optional, not used - using OpenCV)
- opencv-python
- pygame
- websockets
- ffmpeg (for audio extraction)

Install:
```bash
pip install opencv-python pygame websockets PyQt6
```

## Room Configuration

- Default room: `video-sync`
- Override with: `PARTYKIT_ROOM=your-room-name` (and update `main.py`)