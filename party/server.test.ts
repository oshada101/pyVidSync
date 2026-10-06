import { beforeEach, describe, expect, it } from "vitest";
import type * as Party from "partykit/server";
import Server from "./server";

type Msg = Record<string, any>;

class FakeConn {
  sent: string[] = [];
  closed: { code?: number; reason?: string } | null = null;
  constructor(public id: string) {}
  send(data: string) {
    this.sent.push(data);
  }
  close(code?: number, reason?: string) {
    this.closed = { code, reason };
  }
  get msgs(): Msg[] {
    return this.sent.map((s) => JSON.parse(s));
  }
  ofType(type: string): Msg[] {
    return this.msgs.filter((m) => m.type === type);
  }
}

class FakeRoom {
  conns = new Map<string, FakeConn>();
  broadcasts: { msg: string; without?: string[] }[] = [];
  constructor(public id: string) {}
  broadcast(msg: string, without: string[] = []) {
    this.broadcasts.push({ msg, without });
    for (const c of this.conns.values()) if (!without.includes(c.id)) c.send(msg);
  }
  getConnections() {
    return this.conns.values();
  }
}

const ROOM = "ABCD-1234";
const T = (c: string) => c.repeat(20); // valid 20-char token
const TOKEN_A = T("a");
const TOKEN_B = T("b");
const TOKEN_C = T("c");

let room: FakeRoom;
let server: Server;

beforeEach(() => {
  room = new FakeRoom(ROOM);
  server = new Server(room as unknown as Party.Room);
});

function connect(id: string, role: string, token: string): FakeConn {
  const conn = new FakeConn(id);
  room.conns.set(id, conn);
  const url = `https://x.partykit.dev/parties/main/${ROOM}?role=${role}&token=${token}`;
  server.onConnect(conn as unknown as Party.Connection, { request: { url } } as Party.ConnectionContext);
  return conn;
}

const as = (c: FakeConn) => c as unknown as Party.Connection;
const say = (c: FakeConn, msg: unknown) => server.onMessage(typeof msg === "string" ? msg : JSON.stringify(msg), as(c));
const drop = (c: FakeConn) => {
  room.conns.delete(c.id);
  server.onClose(as(c));
};
const clear = (...cs: FakeConn[]) => cs.forEach((c) => (c.sent.length = 0));

const goodSync = { type: "sync", state: "playing", videoTime: 12.5, wallClock: 1700000000.5, filename: "a.mp4" };

describe("connection validation", () => {
  it("rejects invalid room", () => {
    room.id = "bad-room";
    const c = connect("h", "host", TOKEN_A);
    expect(c.msgs).toEqual([{ type: "error", code: "invalid_room" }]);
    expect(c.closed).toEqual({ code: 4000, reason: "invalid_room" });
    expect(server.peers).toEqual([]);
    expect(server.ownerToken).toBeNull();
  });

  it.each(["short", "has space 0123456789", "x".repeat(129), "bad!chars-0123456789"])(
    "rejects invalid token %j",
    (token) => {
      const c = connect("h", "host", encodeURIComponent(token));
      expect(c.msgs).toEqual([{ type: "error", code: "invalid_token" }]);
      expect(c.closed).toEqual({ code: 4001, reason: "invalid_token" });
      expect(server.peers).toEqual([]);
    },
  );

  it("rejects missing token", () => {
    const conn = new FakeConn("h");
    server.onConnect(as(conn), { request: { url: `https://x/parties/main/${ROOM}?role=host` } } as Party.ConnectionContext);
    expect(conn.closed?.code).toBe(4001);
  });

  it("treats unknown role as viewer", () => {
    connect("h", "host", TOKEN_A);
    const v = connect("v", "admin", TOKEN_B);
    expect(v.ofType("welcome")[0]!.role).toBe("viewer");
  });
});

describe("join flow", () => {
  it("first host becomes host", () => {
    const h = connect("h", "host", TOKEN_A);
    expect(h.msgs).toEqual([{ type: "welcome", peerId: "h", role: "host", hostId: "h", peers: ["h"] }]);
    expect(server.hostId).toBe("h");
    expect(server.ownerToken).toBe(TOKEN_A);
  });

  it("viewer into empty room gets room_not_found and is not registered", () => {
    const v = connect("v", "viewer", TOKEN_A);
    expect(v.msgs).toEqual([{ type: "error", code: "room_not_found" }]);
    expect(v.closed).toEqual({ code: 4004, reason: "room_not_found" });
    expect(server.peers).toEqual([]);
    expect(server.tokens.size).toBe(0);

    server.onClose(as(v)); // must not touch state
    expect(room.broadcasts).toEqual([]);
    expect(server.hostId).toBeNull();
  });

  it("viewer join gets welcome with role viewer + hostId; others get peer_joined", () => {
    const h = connect("h", "host", TOKEN_A);
    clear(h);
    const v = connect("v", "viewer", TOKEN_B);
    expect(v.msgs).toEqual([{ type: "welcome", peerId: "v", role: "viewer", hostId: "h", peers: ["h", "v"] }]);
    expect(h.msgs).toEqual([{ type: "peer_joined", peerId: "v", joinIndex: 1 }]);
  });

  it("host with wrong token joins as viewer without changing host", () => {
    const h = connect("h", "host", TOKEN_A);
    clear(h);
    const x = connect("x", "host", TOKEN_B);
    expect(x.ofType("welcome")[0]).toMatchObject({ role: "viewer", hostId: "h" });
    expect(server.hostId).toBe("h");
    expect(server.ownerToken).toBe(TOKEN_A);
    expect(h.ofType("host_changed")).toEqual([]);
  });

  it("rejects a conn id that is already registered (client-chosen _pk)", () => {
    connect("h", "host", TOKEN_A);
    const evil = connect("h", "viewer", TOKEN_B);
    expect(evil.closed?.code).toBe(4002);
    expect(server.peers).toEqual(["h"]);
    say(evil, goodSync); // spoofing host id must not relay
    expect(room.broadcasts.filter((b) => b.msg.includes('"sync"'))).toEqual([]);
    drop(evil); // must not remove the real host
    expect(server.peers).toEqual(["h"]);
    expect(server.hostId).toBe("h");
  });
});

describe("message handling", () => {
  let h: FakeConn, v: FakeConn;
  beforeEach(() => {
    h = connect("h", "host", TOKEN_A);
    v = connect("v", "viewer", TOKEN_B);
    clear(h, v);
  });

  it("drops sync from non-host", () => {
    say(v, goodSync);
    expect(h.sent).toEqual([]);
    expect(v.sent).toEqual([]);
  });

  it("relays sync from host with whitelisted fields + senderId, not to sender", () => {
    say(h, { ...goodSync, evil: "x", senderId: "spoof" });
    expect(h.sent).toEqual([]);
    expect(v.msgs).toEqual([{ ...goodSync, senderId: "h" }]);
  });

  it("relays heartbeat and defaults filename to empty string", () => {
    say(h, { type: "heartbeat", state: "paused", videoTime: 0, wallClock: 5 });
    expect(v.msgs).toEqual([
      { type: "heartbeat", state: "paused", videoTime: 0, wallClock: 5, filename: "", senderId: "h" },
    ]);
  });

  it.each([
    ["missing wallClock", { type: "sync", state: "playing", videoTime: 1 }],
    ["NaN videoTime (null)", { ...goodSync, videoTime: null }],
    ["string wallClock", { ...goodSync, wallClock: "1" }],
    ["bad state", { ...goodSync, state: "stopped" }],
    ["negative videoTime", { ...goodSync, videoTime: -1 }],
    ["non-string filename", { ...goodSync, filename: 5 }],
    ["long filename", { ...goodSync, filename: "x".repeat(256) }],
  ])("drops malformed sync: %s", (_name, msg) => {
    say(h, msg);
    expect(v.sent).toEqual([]);
  });

  it("drops sync with Infinity/NaN (non-JSON numbers via raw text)", () => {
    say(h, '{"type":"sync","state":"playing","videoTime":NaN,"wallClock":1}');
    say(h, '{"type":"sync","state":"playing","videoTime":1e999,"wallClock":1}'); // parses to Infinity
    expect(v.sent).toEqual([]);
  });

  it.each(["1", "null", "[]", '"str"', "true", "not json", "{", "", '{"type":5}', "{}"])(
    "ignores non-object / untyped message %j without throwing",
    (raw) => {
      expect(() => say(h, raw)).not.toThrow();
      expect(() => say(v, raw)).not.toThrow();
      expect(h.sent).toEqual([]);
      expect(v.sent).toEqual([]);
    },
  );

  it("ignores oversized and non-string messages", () => {
    say(h, JSON.stringify({ ...goodSync, filename: "x".repeat(5000) }));
    say(h, JSON.stringify({ type: "ping", clientTime: 1, pad: "x".repeat(5000) }));
    server.onMessage(new TextEncoder().encode(JSON.stringify(goodSync)), as(h));
    server.onMessage(new ArrayBuffer(8), as(h));
    expect(v.sent).toEqual([]);
    expect(h.sent).toEqual([]);
  });

  it("does not relay spoofed welcome / host_changed / peer_* / unknown types", () => {
    for (const sender of [h, v]) {
      say(sender, { type: "welcome", peerId: "x", role: "host", hostId: "x", peers: [] });
      say(sender, { type: "host_changed", newHostId: "v" });
      say(sender, { type: "peer_joined", peerId: "z" });
      say(sender, { type: "peer_left", peerId: "h" });
      say(sender, { type: "chat", text: "hi" });
    }
    expect(h.sent).toEqual([]);
    expect(v.sent).toEqual([]);
    expect(server.hostId).toBe("h");
  });

  it("ping replies pong only to sender with echoed clientTime", () => {
    say(v, { type: "ping", clientTime: 123.5 });
    expect(h.sent).toEqual([]);
    const [pong] = v.msgs;
    expect(pong).toMatchObject({ type: "pong", clientTime: 123.5 });
    expect(pong!.serverTime).toBeCloseTo(Date.now() / 1000, 0);
  });

  it.each([undefined, "1", null, NaN])("ping with bad clientTime %j gets no reply", (clientTime) => {
    say(v, { type: "ping", clientTime });
    expect(v.sent).toEqual([]);
  });
});

describe("transfer_host", () => {
  let h: FakeConn, v: FakeConn, w: FakeConn;
  beforeEach(() => {
    h = connect("h", "host", TOKEN_A);
    v = connect("v", "viewer", TOKEN_B);
    w = connect("w", "viewer", TOKEN_C);
    clear(h, v, w);
  });

  it("ignores unknown target, self, non-string target", () => {
    for (const targetId of ["nobody", "h", 5, null, undefined]) say(h, { type: "transfer_host", targetId });
    expect(server.hostId).toBe("h");
    expect([h, v, w].flatMap((c) => c.sent)).toEqual([]);
  });

  it("ignores transfer by non-host", () => {
    say(v, { type: "transfer_host", targetId: "v" });
    say(v, { type: "transfer_host", targetId: "w" });
    expect(server.hostId).toBe("h");
    expect(server.ownerToken).toBe(TOKEN_A);
    expect([h, v, w].flatMap((c) => c.sent)).toEqual([]);
  });

  it("valid transfer updates host + ownerToken and broadcasts to all incl. sender", () => {
    say(h, { type: "transfer_host", targetId: "v" });
    expect(server.hostId).toBe("v");
    expect(server.ownerToken).toBe(TOKEN_B);
    for (const c of [h, v, w]) expect(c.msgs).toEqual([{ type: "host_changed", newHostId: "v" }]);

    say(h, goodSync); // old host no longer accepted
    expect(w.msgs).toHaveLength(1);
    say(v, goodSync);
    expect(w.ofType("sync")).toHaveLength(1);
  });

  it("old owner cannot reclaim host after transfer", () => {
    say(h, { type: "transfer_host", targetId: "v" });
    drop(h);
    const h2 = connect("h2", "host", TOKEN_A);
    expect(h2.ofType("welcome")[0]).toMatchObject({ role: "viewer", hostId: "v" });
  });
});

describe("disconnects", () => {
  it("host disconnect promotes earliest viewer", () => {
    const h = connect("h", "host", TOKEN_A);
    const v = connect("v", "viewer", TOKEN_B);
    const w = connect("w", "viewer", TOKEN_C);
    clear(h, v, w);
    drop(h);
    expect(server.hostId).toBe("v");
    expect(server.peers).toEqual(["v", "w"]);
    expect(server.ownerToken).toBe(TOKEN_A); // kept for reclaim
    expect(v.msgs).toEqual([
      { type: "host_changed", newHostId: "v" },
      { type: "peer_left", peerId: "h" },
    ]);
    expect(w.msgs).toEqual(v.msgs);
  });

  it("viewer disconnect only broadcasts peer_left", () => {
    const h = connect("h", "host", TOKEN_A);
    const v = connect("v", "viewer", TOKEN_B);
    clear(h);
    drop(v);
    expect(h.msgs).toEqual([{ type: "peer_left", peerId: "v" }]);
    expect(server.hostId).toBe("h");
  });

  it("owner reconnect with same token reclaims host and demotes promoted viewer", () => {
    const h = connect("h", "host", TOKEN_A);
    const v = connect("v", "viewer", TOKEN_B);
    drop(h);
    expect(server.hostId).toBe("v");
    clear(v);

    const h2 = connect("h2", "host", TOKEN_A);
    expect(server.hostId).toBe("h2");
    expect(server.peers).toEqual(["v", "h2"]);
    expect(h2.msgs).toEqual([{ type: "welcome", peerId: "h2", role: "host", hostId: "h2", peers: ["v", "h2"] }]);
    expect(v.msgs).toEqual([
      { type: "host_changed", newHostId: "h2" },
      { type: "peer_joined", peerId: "h2", joinIndex: 1 },
    ]);

    say(v, goodSync); // demoted viewer no longer relays
    expect(h2.ofType("sync")).toEqual([]);
    say(h2, goodSync);
    expect(v.ofType("sync")).toHaveLength(1);
  });

  it("empty room resets owner state so a new owner can claim it", () => {
    const h = connect("h", "host", TOKEN_A);
    drop(h);
    expect(server.peers).toEqual([]);
    expect(server.hostId).toBeNull();
    expect(server.ownerToken).toBeNull();
    expect(server.tokens.size).toBe(0);

    const x = connect("x", "host", TOKEN_B);
    expect(x.ofType("welcome")[0]).toMatchObject({ role: "host", hostId: "x" });
    expect(server.ownerToken).toBe(TOKEN_B);
  });

  it("onClose / onError are idempotent", () => {
    const h = connect("h", "host", TOKEN_A);
    const v = connect("v", "viewer", TOKEN_B);
    clear(h);
    server.onError(as(v), new Error("boom"));
    server.onClose(as(v));
    server.onClose(as(v));
    expect(h.msgs).toEqual([{ type: "peer_left", peerId: "v" }]);
    expect(server.peers).toEqual(["h"]);
  });
});

describe("secrets", () => {
  it("tokens never appear in any sent payload", () => {
    const h = connect("h", "host", TOKEN_A);
    const v = connect("v", "viewer", TOKEN_B);
    const w = connect("w", "host", TOKEN_C);
    say(h, goodSync);
    say(v, { type: "ping", clientTime: 1 });
    say(h, { type: "transfer_host", targetId: "v" });
    drop(v);
    connect("h2", "host", TOKEN_A);
    const all = [h, v, w, ...room.conns.values()].flatMap((c) => c.sent).concat(room.broadcasts.map((b) => b.msg));
    expect(all.length).toBeGreaterThan(5);
    for (const payload of all) for (const t of [TOKEN_A, TOKEN_B, TOKEN_C]) expect(payload).not.toContain(t);
  });
});
