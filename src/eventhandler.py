from _collections_abc import Awaitable, Callable
from typing import Any, Dict, List
import asyncio


Listener = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EventHandler():
    def __init__(self):
        self._listeners: Dict[str, List[Listener]] = {}
        pass

    def add_listener(self, event: str, cb: Listener) -> None:
        self._listeners.setdefault(event, []).append(cb)

    def remove_listener(self, event: str, cb: Listener) -> None:
        self._listeners.get(event, []).remove(cb)
    
    async def call_event(self, event: str, payload: Dict[str, Any] | None = None) -> None:
        payload = payload or {}
        cbs = self._listeners.get(event, [])
        if not cbs:
            return
        
        await asyncio.gather(
            *(cb(event, payload) for cb in cbs),
            return_exceptions=True,
        )