import asyncio
import websockets
import json
import os
from collections import defaultdict

# Хранилище комнат: game_id -> список websocket-клиентов
rooms = defaultdict(list)

async def handler(websocket):
    game_id = None
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            game_id = data.get("game_id")

            if not game_id:
                await websocket.send(json.dumps({"error": "game_id is required"}))
                continue

            if action == "join":
                rooms[game_id].append(websocket)
                player_count = len(rooms[game_id])
                await broadcast(game_id, {
                    "action": "player_joined",
                    "players": player_count,
                    "message": f"Player joined. Total: {player_count}"
                })
                print(f"Player joined game {game_id} | Total: {player_count}")

            elif action == "move":
                await broadcast(game_id, data, exclude=websocket)

            elif action == "chat":
                await broadcast(game_id, data)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if game_id and websocket in rooms.get(game_id, []):
            rooms[game_id].remove(websocket)
            if not rooms[game_id]:
                del rooms[game_id]
            else:
                await broadcast(game_id, {"action": "player_left"})

async def broadcast(game_id, message, exclude=None):
    if game_id not in rooms:
        return
    msg_str = json.dumps(message) if isinstance(message, dict) else str(message)
    for client in rooms[game_id][:]:
        if client != exclude and client.open:
            try:
                await client.send(msg_str)
            except:
                pass

async def main():
    port = int(os.environ.get("PORT", 7778))
    async with websockets.serve(handler, "0.0.0.0", port):
        print(f"Relay сервер запущен на порту {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
