import asyncio, json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from . import state

router = APIRouter()

@router.websocket("/ws/sessions/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    if session_id not in state.ws_subscribers:
        state.ws_subscribers[session_id] = []
    state.ws_subscribers[session_id].append(queue)
    try:
        # Send existing state on connect
        if session_id in state.match_states:
            await websocket.send_json({"type": "match_state.update", "payload": state.match_states[session_id]})
        for ev in state.events.get(session_id, []):
            await websocket.send_json({"type": "event.created", "payload": ev})
        for line in state.commentary.get(session_id, [])[-20:]:
            await websocket.send_json({"type": "commentary.line", "payload": line})

        # Fan out new events
        async def send_loop():
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)

        async def recv_loop():
            while True:
                data = await websocket.receive_json()
                # Handle client events
                if data.get("type") == "query.submit":
                    # TODO: wire to retrieval pipeline
                    pass

        await asyncio.gather(send_loop(), recv_loop())
    except WebSocketDisconnect:
        pass
    finally:
        state.ws_subscribers[session_id].remove(queue)
