import type * as Party from "partykit/server";

interface RoomState {
  peers: string[];
  hostId: string | null;
}

const rooms = new Map<string, RoomState>();

function getRoom(roomId: string): RoomState {
  if (!rooms.has(roomId)) {
    rooms.set(roomId, { peers: [], hostId: null });
  }
  return rooms.get(roomId)!;
}

export default {
  onConnect(conn: Party.Connection, room: Party.Room, ctx: Party.ConnectionContext) {
    const state = getRoom(room.id);
    const isFirst = state.peers.length === 0;

    state.peers.push(conn.id);

    if (isFirst) {
      state.hostId = conn.id;
    }

    conn.send(JSON.stringify({
      type: "welcome",
      peerId: conn.id,
      role: isFirst ? "host" : "viewer",
      peers: [...state.peers],
    }));

    const joinIndex = state.peers.length - 1;
    room.broadcast(
      JSON.stringify({ type: "peer_joined", peerId: conn.id, joinIndex }),
      [conn.id],
    );
  },

  onMessage(message: string, sender: Party.Connection, room: Party.Room) {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(message) as Record<string, unknown>;
    } catch {
      return;
    }

    if (parsed.type === "transfer_host") {
      const state = getRoom(room.id);
      if (state.hostId !== sender.id) return;
      const targetId = parsed.targetId as string;
      state.hostId = targetId;
      room.broadcast(JSON.stringify({ type: "host_changed", newHostId: targetId }));
      return;
    }

    parsed.senderId = sender.id;
    room.broadcast(JSON.stringify(parsed), [sender.id]);
  },

  onClose(conn: Party.Connection, room: Party.Room) {
    const state = getRoom(room.id);

    state.peers = state.peers.filter((id) => id !== conn.id);

    if (state.hostId === conn.id) {
      state.hostId = state.peers[0] ?? null;
      if (state.hostId !== null) {
        room.broadcast(JSON.stringify({ type: "host_changed", newHostId: state.hostId }));
      }
    }

    room.broadcast(JSON.stringify({ type: "peer_left", peerId: conn.id }));

    if (state.peers.length === 0) {
      rooms.delete(room.id);
    }
  },
} satisfies Party.Server;
