import asyncio
import json
import websockets
import os
import ssl
from dotenv import load_dotenv

load_dotenv()


class PartyKitClient:
    def __init__(self, room_id: str = "video-sync"):
        self.room_id = room_id
        self.host = os.environ.get("PARTYKIT_HOST")
        self.ws = None
        self.on_message_callback = None
        self.on_connect_callback = None
    
    async def connect(self):
        is_local = self.host in ("localhost:1999", "127.0.0.1:1999")
        scheme = "ws" if is_local else "wss"
        uri = f"{scheme}://{self.host}/parties/main/{self.room_id}"
        print(f"[PartyKit] Connecting to: {uri}")
        
        self.ws = await websockets.connect(uri)
        print(f"[PartyKit] Connected to room: {self.room_id}")
        
        if self.on_connect_callback:
            self.on_connect_callback()
        
        await self._receive_messages()
    
    async def _receive_messages(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                print(f"[PartyKit] Received: {data}")
                
                if self.on_message_callback:
                    self.on_message_callback(data)
                    
        except Exception as e:
            print(f"[PartyKit] Error: {e}")
    
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