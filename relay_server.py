import asyncio
import websockets
import json
import os
import http
from collections import defaultdict

# room_id -> set of websockets
rooms = defaultdict(set)

# websocket -> room_id
user_room = {}

# websocket -> game_id (фиксируем один раз)
user_game = {}

# ================= HEALTH CHECK =================
async def process_request(path, request_headers):
    if path in ("/", "/healthz", "/health"):
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"OK\n"
    return None

# ================= BROADCAST =================
async def broadcast(game_id, message, exclude=None):
    if game_id not in rooms:
        return

    msg = json.dumps(message, ensure_ascii=False)

    for client in list(rooms[game_id]):
        if client != exclude:
            try:
                await client.send(msg)
            except:
                pass

# ================= HANDLER =================
async def handler(websocket):
    game_id = None

    try:
        async for message in websocket:

            try:
                data = json.loads(message)
            except:
                continue

            # 🔥 FIX: поддержка Unity формата
            action = data.get("action")
            game_id = data.get("game_id") or data.get("gameId")

            if not action:
                continue

            # ================= JOIN =================
            if action == "join":

                if not game_id:
                    await websocket.send(json.dumps({"error": "game_id required"}))
                    continue

                game_id = game_id.upper()

                rooms[game_id].add(websocket)
                user_room[websocket] = game_id
                user_game[websocket] = game_id

                count = len(rooms[game_id])

                await broadcast(game_id, {
                    "action": "player_joined",
                    "players": count,
                    "game_id": game_id,
                    "message": f"Игрок подключился. Всего: {count}"
                })

            # ================= MOVE =================
            elif action == "move":

                game_id = user_room.get(websocket)

                if not game_id:
                    continue

                await broadcast(game_id, {
                    "action": "move",
                    "data": data
                }, exclude=websocket)

            # ================= CHAT =================
            elif action == "chat":

                game_id = user_room.get(websocket)

                if not game_id:
                    continue

                await broadcast(game_id, {
                    "action": "chat",
                    "data": data
                })

    except Exception as e:
        print("Handler error:", e)

    finally:
        # ================= CLEANUP =================
        game_id = user_room.get(websocket)

        if game_id and websocket in rooms[game_id]:
            rooms[game_id].remove(websocket)

            if len(rooms[game_id]) > 0:
                await broadcast(game_id, {
                    "action": "player_left"
                })
            else:
                del rooms[game_id]

        user_room.pop(websocket, None)
        user_game.pop(websocket, None)

# ================= MAIN =================
async def main():
    port = int(os.environ.get("PORT", 10000))

    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=30
    ):
        print(f"✅ Server running on port {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
