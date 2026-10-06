import type * as Party from "partykit/server";

const ROOM_RE = /^[A-Z]{4}-\d{4}$/;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
const MAX_MESSAGE_LEN = 4096;
const MAX_FILENAME_LEN = 255;

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** One instance per room (hibernation is off), so room state lives in fields. */
export default class Server implements Party.Server {
  peers: string[] = [];
  hostId: string | null = null;
  ownerToken: string | null = null;
  /** connId -> secret token. Never sent to any client. */
  tokens = new Map<string, string>();
  /**
   * Connections turned away in onConnect. Clients can pick their own conn id
   * (`?_pk=`), so a rejected socket may carry a registered peer's id and must
   * never act on, or clean up after, that peer.
   */
  private rejected = new WeakSet<Party.Connection>();

  constructor(readonly room: Party.Room) {}

  onConnect(conn: Party.Connection, ctx: Party.ConnectionContext) {
    const params = new URL(ctx.request.url).searchParams;
    const token = params.get("token") ?? "";

    if (!ROOM_RE.test(this.room.id)) return this.reject(conn, "invalid_room", 4000);
    if (!TOKEN_RE.test(token)) return this.reject(conn, "invalid_token", 4001);
    if (this.peers.includes(conn.id)) return this.reject(conn, "invalid_id", 4002);

    let isHost = false;
    if (params.get("role") === "host") {
      if (this.ownerToken === null) this.ownerToken = token;
      isHost = token === this.ownerToken;
    } else if (this.peers.length === 0) {
      return this.reject(conn, "room_not_found", 4004);
    }

    this.peers.push(conn.id);
    this.tokens.set(conn.id, token);

    if (isHost && this.hostId !== conn.id) {
      const prev = this.hostId;
      this.hostId = conn.id;
      if (prev !== null) this.broadcast({ type: "host_changed", newHostId: conn.id }, [conn.id]);
    }

    this.send(conn, {
      type: "welcome",
      peerId: conn.id,
      role: this.hostId === conn.id ? "host" : "viewer",
      hostId: this.hostId,
      peers: [...this.peers],
    });
    this.broadcast(
      { type: "peer_joined", peerId: conn.id, joinIndex: this.peers.length - 1 },
      [conn.id],
    );
  }

  onMessage(message: string | ArrayBuffer | ArrayBufferView, sender: Party.Connection) {
    if (this.rejected.has(sender)) return;
    if (typeof message !== "string" || message.length > MAX_MESSAGE_LEN) return;

    let parsed: unknown;
    try {
      parsed = JSON.parse(message);
    } catch {
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return;
    const msg = parsed as Record<string, unknown>;

    switch (msg.type) {
      case "ping":
        if (isNum(msg.clientTime)) {
          this.send(sender, { type: "pong", clientTime: msg.clientTime, serverTime: Date.now() / 1000 });
        }
        return;

      case "sync":
      case "heartbeat": {
        if (sender.id !== this.hostId) return;
        const { state, videoTime, wallClock, filename = "" } = msg;
        if (
          (state !== "playing" && state !== "paused") ||
          !isNum(videoTime) || videoTime < 0 ||
          !isNum(wallClock) ||
          typeof filename !== "string" || filename.length > MAX_FILENAME_LEN
        ) return;
        // Rebuild from validated fields only; never relay the raw object.
        this.broadcast(
          { type: msg.type, state, videoTime, wallClock, filename, senderId: sender.id },
          [sender.id],
        );
        return;
      }

      case "transfer_host": {
        const { targetId } = msg;
        if (
          sender.id !== this.hostId ||
          typeof targetId !== "string" || targetId === sender.id ||
          !this.peers.includes(targetId)
        ) return;
        this.hostId = targetId;
        this.ownerToken = this.tokens.get(targetId) ?? null;
        this.broadcast({ type: "host_changed", newHostId: targetId });
        return;
      }
    }
  }

  onClose(conn: Party.Connection) {
    this.leave(conn);
  }

  onError(conn: Party.Connection, _err: Error) {
    this.leave(conn);
  }

  /** Idempotent: a no-op for connections that were rejected or already removed. */
  private leave(conn: Party.Connection) {
    if (this.rejected.has(conn)) return;
    const i = this.peers.indexOf(conn.id);
    if (i === -1) return;

    this.peers.splice(i, 1);
    this.tokens.delete(conn.id);

    if (this.hostId === conn.id) {
      this.hostId = this.peers[0] ?? null;
      // ownerToken is kept so the owner can reclaim host after reconnecting.
      if (this.hostId !== null) this.broadcast({ type: "host_changed", newHostId: this.hostId });
    }
    this.broadcast({ type: "peer_left", peerId: conn.id });

    if (this.peers.length === 0) {
      this.hostId = null;
      this.ownerToken = null;
      this.tokens.clear();
    }
  }

  private reject(conn: Party.Connection, code: string, closeCode: number) {
    this.rejected.add(conn);
    this.send(conn, { type: "error", code });
    conn.close(closeCode, code);
  }

  private send(conn: Party.Connection, msg: object) {
    conn.send(JSON.stringify(msg));
  }

  private broadcast(msg: object, without?: string[]) {
    this.room.broadcast(JSON.stringify(msg), without);
  }
}
