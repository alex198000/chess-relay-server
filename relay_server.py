import asyncio
import websockets
import json
import os
import http
from collections import defaultdict

rooms = defaultdict(list)

# ✅ Улучшенный Health Check для Render
async def process_request(path, request_headers):
    if path in ("/", "/healthz", "/health"):
        response_headers = [("Content-Type", "text/plain")]
        return http.HTTPStatus.OK, response_headers, b"OK\n"
    # Если это не health check — продолжаем как WebSocket
    return None

async def handler(websocket):
    game_id = None
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except:
                continue

            action = data.get("action")
            game_id = data.get("game_id")

            if not game_id:
                await websocket.send(json.dumps({"error": "game_id is required"}))
                continue

            if action == "join":
                rooms[game_id].append(websocket)
                count = len(rooms[game_id])
                await broadcast(game_id, {"action": "player_joined", "players": count, "message": f"Игрок подключился. Всего: {count}"})

            elif action == "move":
                await broadcast(game_id, data, exclude=websocket)

            elif action == "chat":
                await broadcast(game_id, data)

    except Exception as e:
        print(f"Handler error: {e}")
    finally:
        if game_id and websocket in rooms.get(game_id, []):
            rooms[game_id].remove(websocket)
            if rooms[game_id]:
                await broadcast(game_id, {"action": "player_left"})
            else:
                del rooms[game_id]

async def broadcast(game_id, message, exclude=None):
    if game_id not in rooms:
        return
    msg = json.dumps(message) if isinstance(message, dict) else str(message)
    for client in list(rooms[game_id]):
        if client != exclude and client.open:
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
        ping_interval=20,      # держит соединение живым
        ping_timeout=30
    ):
        print(f"✅ Relay сервер успешно запущен на порту {port}")
        print("Health check /healthz настроен")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
