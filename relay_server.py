import argparse
import asyncio
import json
import os
from typing import Any

from aiohttp import WSMsgType, web

rooms: dict[str, dict[str, web.WebSocketResponse | None]] = {}

# =========================
# METRICS
# =========================
metrics = {
    "total_connections": 0,
    "active_connections": 0,
    "messages_relayed": 0,
    "rooms_created": 0,
    "disconnects": 0,
}


def inc(name: str, value: int = 1) -> None:
    metrics[name] = metrics.get(name, 0) + value


def get_peer(room_id: str, ws: web.WebSocketResponse) -> web.WebSocketResponse | None:
    room = rooms.get(room_id)
    if not room:
        return None
    if room.get("host") is ws:
        return room.get("guest")
    if room.get("guest") is ws:
        return room.get("host")
    return None


async def send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> None:
    await ws.send_str(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


async def relay_socket(ws: web.WebSocketResponse) -> None:
    room_id: str | None = None

    inc("total_connections")
    inc("active_connections")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                raw = msg.data
            elif msg.type == WSMsgType.BINARY:
                raw = msg.data.decode("utf-8", errors="replace")
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            else:
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = str(data.get("action") or "").strip().lower()
            gid = data.get("game_id") or data.get("gameId")
            gid = gid.strip().upper() if isinstance(gid, str) else None

            # =========================
            # JOIN ROOM
            # =========================
            if action in ("join", "register", "connect", "enter", "handshake") and gid:
                room_id = gid

                is_new_room = room_id not in rooms
                room = rooms.setdefault(room_id, {"host": None, "guest": None})

                if is_new_room:
                    inc("rooms_created")

                is_host = bool(data.get("host"))
                slot = "host" if is_host else "guest"

                old = room.get(slot)
                if old is not None and old is not ws:
                    try:
                        await old.close()
                    except Exception:
                        pass

                room[slot] = ws

                await send_json(
                    ws,
                    {
                        "action": "player_joined",
                        "game_id": room_id,
                        "message": f"Room {room_id} - {'host' if is_host else 'guest'} joined.",
                    },
                )

                peer = get_peer(room_id, ws)
                if peer is not None and not peer.closed:
                    name = data.get("sender") or "Player"
                    await send_json(
                        peer,
                        {
                            "action": "player_joined",
                            "game_id": room_id,
                            "message": f"Opponent ({name}) joined.",
                        },
                    )
                continue

            if room_id is None:
                await send_json(ws, {"error": "Send a Join message with game_id and host first."})
                continue

            if gid and gid != room_id:
                room_id = gid

            peer = get_peer(room_id, ws)
            if peer is None or peer.closed:
                await send_json(
                    ws,
                    {
                        "action": "status",
                        "game_id": room_id,
                        "message": "Waiting for opponent in this room...",
                    },
                )
                continue

            try:
                await peer.send_str(raw)
                inc("messages_relayed")
            except Exception:
                pass

    finally:
        inc("disconnects")
        inc("active_connections", -1)

        if room_id and room_id in rooms:
            room = rooms[room_id]

            for key in ("host", "guest"):
                if room.get(key) is ws:
                    room[key] = None

            peer = get_peer(room_id, ws)
            if peer is not None and not peer.closed:
                try:
                    await send_json(
                        peer,
                        {
                            "action": "player_joined",
                            "game_id": room_id,
                            "message": "Opponent disconnected.",
                        },
                    )
                except Exception:
                    pass

            if room.get("host") is None and room.get("guest") is None:
                rooms.pop(room_id, None)


async def http_or_ws(request: web.Request) -> web.StreamResponse:
    path = request.path.split("?")[0]

    # =========================
    # METRICS ENDPOINT
    # =========================
    if path == "/metrics":
        return web.json_response(metrics)

    if path not in ("/", "/healthz", "/health", "/metrics"):
        raise web.HTTPNotFound()

    if request.headers.get("Upgrade", "").lower() != "websocket":
        if request.method == "HEAD":
            return web.Response(status=200, body=b"")
        if request.method == "GET":
            return web.Response(text="OK\n")
        raise web.HTTPMethodNotAllowed(request.method, ("GET", "HEAD"))

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await relay_socket(ws)
    return ws


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("BIND_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "10000")))
    args = parser.parse_args()

    app = web.Application()
    for p in ("/", "/healthz", "/health", "/metrics"):
        app.router.add_route("*", p, http_or_ws)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    print(f"Relay started on {args.host}:{args.port}")
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
