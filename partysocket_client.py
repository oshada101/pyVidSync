import asyncio
import json
import websockets
import os
import sys
import ssl
from dotenv import load_dotenv

if not getattr(sys, 'frozen', False):
    load_dotenv()


class PartyKitClient:
    def __init__(self, room_id: str = "video-sync"):
        self.room_id = room_id
        if getattr(sys, 'frozen', False):
            self.host = "python-sync-server.eastcoast.partykit.dev"
        else:
            self.host = os.environ.get("PARTYKIT_HOST")
        self.ws = None
        self.on_message_callback = None
        self.on_connect_callback = None
    
    async def connect(self):
        is_local = self.host in ("localhost:1999", "127.0.0.1:1999")
        scheme = "ws" if is_local else "wss"
        uri = f"{scheme}://{self.host}/parties/main/{self.room_id}"
        print(f"[PartyKit] Connecting to: {uri}")

        while True:
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=5,
                ) as ws:
                    self.ws = ws
                    print(f"[PartyKit] Connected to room: {self.room_id}")
                    if self.on_connect_callback:
                        self.on_connect_callback()
                    await self._receive_messages()
            except Exception as e:
                print(f"[PartyKit] Disconnected: {e} — retrying in 3s")
                self.ws = None
                await asyncio.sleep(3)

    async def _receive_messages(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                print(f"[PartyKit] Received: {data}")
                if self.on_message_callback:
                    self.on_message_callback(data)
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except Exception as e:
            print(f"[PartyKit] Error: {e}")
            raise
    
    async def send(self, message: dict):
        if self.ws:
            await self.ws.send(json.dumps(message))
    
    async def broadcast(self, message: dict):
        await self.send(message)
    
    def set_on_message(self, callback):
        self.on_message_callback = callback
    
    def set_on_connect(self, callback):
        self.on_connect_callback = callback
    
    async def close(self):
        if self.ws:
            await self.ws.close()
        print("[PartyKit] Closed")


async def main():
    client = PartyKitClient("test-room")
    await client.connect()


if __name__ == "__main__":
    asyncio.run(main())