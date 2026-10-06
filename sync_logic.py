"""Pure sync/protocol helpers. No Qt or VLC imports, so everything here is unit-testable."""
import ipaddress
import math
import re
import secrets
import string
from collections import deque
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

ROOM_CODE_RE = re.compile(r"^[A-Z]{4}-\d{4}$")
SYNC_STATES = ("playing", "paused")
DRIFT_THRESHOLD_SEC = 0.75


def generate_room_code() -> str:
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"{letters}-{digits}"


def normalize_room_code(raw: str) -> str | None:
    code = raw.strip().upper()
    return code if ROOM_CODE_RE.fullmatch(code) else None


def generate_token() -> str:
    """Per-session secret that lets a host reclaim its room after a reconnect."""
    return secrets.token_urlsafe(24)


def normalize_host(raw: str) -> str | None:
    """Accept 'example.partykit.dev', 'localhost:1999' or an explicit ws:// / wss:// URL.

    http(s):// is mapped to ws(s):// for convenience. Returns None if the value is unusable.
    """
    host = raw.strip()
    for web, ws in (("https://", "wss://"), ("http://", "ws://")):
        if host.startswith(web):
            host = ws + host[len(web):]
    scheme, sep, netloc = host.rpartition("://")
    if sep and scheme not in ("ws", "wss"):
        return None
    netloc = netloc.rstrip("/")
    if not netloc or any(c in netloc for c in "/?# "):
        return None
    return f"{scheme}://{netloc}" if sep else netloc


def build_ws_uri(host: str, room_id: str, role: str, token: str) -> str:
    """`host` must already be normalized. Loopback hosts without a scheme default to ws://."""
    if "://" in host:
        base = host
    else:
        base = f"{'ws' if _is_loopback(host) else 'wss'}://{host}"
    query = urlencode({"role": role, "token": token})
    return f"{base}/parties/main/{quote(room_id, safe='')}?{query}"


def _is_loopback(host: str) -> bool:
    hostname = urlsplit(f"//{host}").hostname or ""
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class SyncState:
    state: str
    video_time: float
    wall_clock: float  # server clock, seconds
    filename: str = ""


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_sync(msg: dict) -> SyncState | None:
    """Validate a sync/heartbeat payload; None if any field is missing or malformed."""
    state = msg.get("state")
    video_time = msg.get("videoTime")
    wall_clock = msg.get("wallClock")
    filename = msg.get("filename", "")
    if state not in SYNC_STATES or not is_number(video_time) or not is_number(wall_clock):
        return None
    if video_time < 0:
        return None
    return SyncState(state, float(video_time), float(wall_clock), filename if isinstance(filename, str) else "")


def expected_position(sync: SyncState, now: float, duration: float = 0.0) -> float:
    """Where the host's playhead should be at `now` (same clock as `sync.wall_clock`)."""
    position = sync.video_time
    if sync.state == "playing":
        position += max(0.0, now - sync.wall_clock)
    if duration > 0:
        position = min(position, duration)
    return max(0.0, position)


def needs_correction(local: float, expected: float, threshold: float = DRIFT_THRESHOLD_SEC) -> bool:
    return abs(local - expected) > threshold


class ClockSync:
    """Estimates this machine's offset to the server clock from ping/pong samples (NTP-style).

    Uses the lowest-RTT sample in a recent window: queueing delay only ever inflates RTT,
    so the fastest round trip gives the tightest offset estimate.
    """

    def __init__(self, window: int = 8):
        self._samples: deque[tuple[float, float]] = deque(maxlen=window)  # (rtt, offset)
        self.offset = 0.0

    def add_sample(self, client_send: float, server_time: float, client_recv: float) -> None:
        rtt = client_recv - client_send
        if rtt < 0:
            return
        self._samples.append((rtt, server_time - (client_send + client_recv) / 2))
        self.offset = min(self._samples)[1]

    def now(self, local_time: float) -> float:
        return local_time + self.offset
