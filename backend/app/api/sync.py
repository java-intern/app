import asyncio
import json
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.utils.security import require_admin_role

router = APIRouter(prefix="/sync", tags=["Real-time Sync & Events"])
logger = logging.getLogger(__name__)

class EventBroadcaster:
    def __init__(self) -> None:
        # Map company_id -> list of asyncio.Queue instances
        self.connections: dict[str, list[asyncio.Queue]] = {}

    def connect(self, company_id: str) -> asyncio.Queue:
        """Register a new admin connection queue for a company."""
        q = asyncio.Queue()
        if company_id not in self.connections:
            self.connections[company_id] = []
        self.connections[company_id].append(q)
        return q

    def disconnect(self, company_id: str, q: asyncio.Queue) -> None:
        """Unregister an admin connection queue."""
        if company_id in self.connections:
            if q in self.connections[company_id]:
                self.connections[company_id].remove(q)
            if not self.connections[company_id]:
                del self.connections[company_id]

    async def broadcast(self, company_id: str, data: dict) -> None:
        """Broadcast JSON formatted SSE data to all active connections in a company room."""
        if company_id in self.connections:
            event_data = f"data: {json.dumps(data)}\n\n"
            for q in self.connections[company_id]:
                await q.put(event_data)

broadcaster = EventBroadcaster()

async def sse_event_generator(company_id: str):
    """Generates Server-Sent Events (SSE) stream with keep-alive comments."""
    q = broadcaster.connect(company_id)
    try:
        while True:
            try:
                # Wait for next event; timeout after 3 seconds for keep-alive packet
                event = await asyncio.wait_for(q.get(), timeout=3.0)
                yield event
            except asyncio.TimeoutError:
                # Long-lived TCP connection keep-alive
                yield ": keep-alive\n\n"
    except asyncio.CancelledError:
        logger.info(f"SSE client disconnected for company {company_id}")
    finally:
        broadcaster.disconnect(company_id, q)

@router.get("/stream")
async def stream_telemetry_events(
    claims: dict = Depends(require_admin_role)
):
    """
    Establish a long-lived text/event-stream connection to stream telemetry events.
    Restricted to ADMIN role, separated strictly by company_id room.
    """
    company_id = claims["company_id"]
    return StreamingResponse(
        sse_event_generator(company_id),
        media_type="text/event-stream"
    )
