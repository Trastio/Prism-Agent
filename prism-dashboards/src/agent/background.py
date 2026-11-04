from __future__ import annotations

import asyncio
import heapq
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Awaitable, Literal, Optional

logger = logging.getLogger(__name__)

_PRIORITY_VALUE = {"high": 0, "medium": 1, "low": 2}


@dataclass
class RetryPolicy:
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0

    def get_delay(self, attempt: int) -> float:
        delay = self.initial_delay * (2 ** attempt)
        return min(delay, self.max_delay)


@dataclass
class BackgroundTask:
    task_id: str
    task_type: str
    params: dict
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    priority: Literal["high", "medium", "low"] = "medium"
    result: Optional[dict] = None
    error: Optional[str] = None
    failed_reason: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0


_Callback = Callable[[str, str, Optional[dict]], Awaitable[None]]


class BackgroundManager:
    def __init__(self, concurrency: int = 2, persist: bool = True,
                 registry_path: str = ".tasks/background_registry.json",
                 default_retry: RetryPolicy | None = None):
        self.concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self.registry_path = Path(registry_path) if persist else None
        self.default_retry = default_retry or RetryPolicy()
        self.timeouts: dict[str, float] = {}
        self.executors: dict[str, Callable] = {}
        self.tasks: dict[str, BackgroundTask] = {}
        self._callbacks: list[_Callback] = []
        self._running_tasks: set[asyncio.Task] = set()
        self._queue: list[tuple[int, float, str]] = []
        self._queue_event: asyncio.Event | None = None
        self._dispatcher_started = False
        self._load_existing()

    def _get_queue_event(self) -> asyncio.Event:
        if self._queue_event is None:
            self._queue_event = asyncio.Event()
        return self._queue_event

    def _load_existing(self):
        if self.registry_path is None or not self.registry_path.exists():
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            for tid, td in data.items():
                task = BackgroundTask(**{k: v for k, v in td.items()
                                         if k in BackgroundTask.__dataclass_fields__})
                self.tasks[tid] = task
                if task.status == "running":
                    task.status = "failed"
                    task.failed_reason = "进程中断"
                    task.completed_at = datetime.now().isoformat()
                    self._persist_task(task)
        except Exception as e:
            logger.warning("Failed to load background registry: %s", e)

    def register_executor(self, task_type: str, fn: Callable,
                          timeout: float = 300.0):
        self.executors[task_type] = fn
        self.timeouts[task_type] = timeout

    def subscribe(self, callback: _Callback):
        self._callbacks.append(callback)

    async def submit(self, task_type: str, params: dict,
                     priority: str = "medium") -> str:
        if task_type not in self.executors:
            raise ValueError(f"No executor registered for '{task_type}'")
        task_id = str(uuid.uuid4())
        bg_task = BackgroundTask(
            task_id=task_id, task_type=task_type,
            params=params, priority=priority,
        )
        self.tasks[task_id] = bg_task
        self._persist_task(bg_task)
        heapq.heappush(self._queue, (_PRIORITY_VALUE.get(priority, 1),
                                      _counter(), task_id))
        self._get_queue_event().set()
        if not self._dispatcher_started:
            self._dispatcher_started = True
            atask = asyncio.create_task(self._dispatcher())
            self._running_tasks.add(atask)
            atask.add_done_callback(self._running_tasks.discard)
        return task_id

    async def _dispatcher(self):
        while True:
            while self._queue:
                await self._semaphore.acquire()
                if not self._queue:
                    self._semaphore.release()
                    break
                _, _, task_id = heapq.heappop(self._queue)
                bg_task = self.tasks.get(task_id)
                if bg_task and bg_task.status == "pending":
                    atask = asyncio.create_task(self._run(bg_task))
                    self._running_tasks.add(atask)
                    atask.add_done_callback(self._done_callback)
                else:
                    self._semaphore.release()
            event = self._get_queue_event()
            event.clear()
            await event.wait()

    def _done_callback(self, atask: asyncio.Task):
        self._semaphore.release()
        self._running_tasks.discard(atask)

    def check(self, task_id: str) -> Optional[BackgroundTask]:
        return self.tasks.get(task_id)

    async def _run(self, bg_task: BackgroundTask):
        bg_task.status = "running"
        bg_task.started_at = datetime.now().isoformat()
        await self._persist_async(bg_task)

        retry = self.default_retry
        timeout = self.timeouts.get(bg_task.task_type, 300.0)
        for attempt in range(retry.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self.executors[bg_task.task_type](bg_task.params),
                    timeout=timeout,
                )
                bg_task.status = "completed"
                bg_task.result = result
                bg_task.completed_at = datetime.now().isoformat()
                await self._persist_async(bg_task)
                await self._notify(bg_task.task_id, "completed", result)
                return
            except asyncio.TimeoutError:
                bg_task.error = "Timeout"
                bg_task.failed_reason = f"执行超时（{timeout:.0f}秒）"
            except Exception as e:
                bg_task.error = str(e)
                bg_task.failed_reason = str(e)

            bg_task.retry_count = attempt + 1
            if attempt < retry.max_retries:
                delay = retry.get_delay(attempt)
                logger.info("Retrying %s in %.1fs (attempt %d)",
                            bg_task.task_id, delay, attempt + 1)
                await asyncio.sleep(delay)

        bg_task.status = "failed"
        bg_task.completed_at = datetime.now().isoformat()
        await self._persist_async(bg_task)
        await self._notify(bg_task.task_id, "failed", {"error": bg_task.error})

    async def _notify(self, task_id: str, status: str, result: dict | None):
        for cb in self._callbacks:
            try:
                await cb(task_id, status, result)
            except Exception as e:
                logger.warning("Callback error: %s", e)

    async def _persist_async(self, task: BackgroundTask):
        if self.registry_path is None:
            return
        await asyncio.to_thread(self._persist_task, task)

    def _persist_task(self, task: BackgroundTask):
        if self.registry_path is None:
            return
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {tid: asdict(t) for tid, t in self.tasks.items()}
        tmp_path = self.registry_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        os.replace(tmp_path, self.registry_path)

    async def shutdown(self):
        for atask in list(self._running_tasks):
            atask.cancel()
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)


_counter_val = 0


def _counter() -> float:
    global _counter_val
    _counter_val += 1
    return float(_counter_val)


_bg_lock = asyncio.Lock()
_background_manager: BackgroundManager | None = None
_pending_registrations: list[tuple[str, Callable, float]] = []


async def get_background_manager() -> BackgroundManager:
    global _background_manager
    if _background_manager is None:
        async with _bg_lock:
            if _background_manager is None:
                _background_manager = BackgroundManager()
                for name, fn, timeout in _pending_registrations:
                    _background_manager.register_executor(name, fn, timeout=timeout)
                _pending_registrations.clear()
    return _background_manager
