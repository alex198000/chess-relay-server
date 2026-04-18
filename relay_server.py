import asyncio
import websockets
import json
import os
import http
from collections import defaultdict

rooms = defaultdict(list)

# 🔥 ВАЖНО: игнор HTTP запросов (Render health check fix)
async def process_request(path, request_headers):
    if path in ("/", "/healthz", "/health"):
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"OK\n"
    return None  # WebSocket only

async def handler(websocket):
    game_id = None
    try:
        async for message in websocket:

            # 🔥 защита от мусора
            if not isinstance(message, str):
                continue

            try:
                data = json.loads(message)
            except:
                continue

            action = data.get("action")
            game_id = data.get("game_id")

            if not game_id:
                await websocket.send(json.dumps({"error": "game_id required"}))
                continue

            # JOIN
            if action == "join":
                if websocket not in rooms[game_id]:
                    rooms[game_id].append(websocket)

                await broadcast(game_id, {
                    "action": "player_joined",
                    "count": len(rooms[game_id])
                })

            # MOVE
            elif action == "move":
                await broadcast(game_id, data, exclude=websocket)

            # CHAT
            elif action == "chat":
                await broadcast(game_id, data)

    except Exception as e:
        print("Handler error:", e)

    finally:
        if game_id and websocket in rooms.get(game_id, []):
            rooms[game_id].remove(websocket)
            await broadcast(game_id, {"action": "player_left"})

async def broadcast(game_id, message, exclude=None):
    if game_id not in rooms:
        return

    msg = json.dumps(message)

    for client in list(rooms[game_id]):
        if client != exclude:
            try:
                await client.send(msg)
            except:
                pass

async def main():
    port = int(os.environ.get("PORT", 10000))

    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        process_request=process_request,
        ping_interval=25,
        ping_timeout=60
    ):
        print("Server started")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
