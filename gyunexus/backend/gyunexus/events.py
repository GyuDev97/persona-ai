import asyncio
from contextlib import contextmanager
from typing import Any


class EventBus:
    """SSE 엔드포인트에 이벤트를 전달하는 프로세스 내 pub/sub."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def publish(self, type: str, data: Any = None) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait({"type": type, "data": data})
            except asyncio.QueueFull:
                pass  # 느린 구독자는 건너뛴다(발행자를 막지 않기 위해)

    @contextmanager
    def subscribe(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        try:
            yield q
        finally:
            self._subs.discard(q)
