from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal

logger = logging.getLogger(__name__)

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_MUTABLE_FIELDS = frozenset({
    "status", "priority", "parent_id", "blocked_by", "blocks",
    "timeout", "failed_reason", "skipped_reason", "retry_count",
    "max_retries", "user_id", "started_at",
})


@dataclass
class Task:
    id: int
    subject: str
    status: Literal["pending", "in_progress", "completed", "failed", "skipped", "cancelled"] = "pending"
    priority: Literal["high", "medium", "low"] = "medium"
    user_id: str = "default"
    parent_id: Optional[int] = None
    blocked_by: list[int] = field(default_factory=list)
    blocks: list[int] = field(default_factory=list)
    timeout: Optional[int] = None
    failed_reason: Optional[str] = None
    skipped_reason: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaskManager:
    def __init__(self, tasks_dir: str = ".tasks"):
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[int, Task] = {}
        self.next_id = 1
        self._lock = asyncio.Lock()
        self._load_existing()

    def _load_existing(self):
        for f in sorted(self.tasks_dir.glob("task_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = Task.from_dict(data)
                self.tasks[task.id] = task
                if task.id >= self.next_id:
                    self.next_id = task.id + 1
            except Exception as e:
                logger.warning("Failed to load task from %s: %s", f, e)

    async def create(self, subject: str, **kwargs) -> Task:
        async with self._lock:
            task = Task(id=self.next_id, subject=subject, **kwargs)
            self.next_id += 1
            self.tasks[task.id] = task
            logger.info("Created task %d: %s", task.id, subject)
            if task.parent_id:
                parent = self.tasks.get(task.parent_id)
                if parent and task.id not in parent.blocks:
                    parent.blocks.append(task.id)
                    self._save(parent)
                elif not parent:
                    logger.warning("parent_id %d not found for task %d", task.parent_id, task.id)
            for blocker_id in task.blocked_by:
                blocker = self.tasks.get(blocker_id)
                if blocker and task.id not in blocker.blocks:
                    blocker.blocks.append(task.id)
                    self._save(blocker)
                elif not blocker:
                    logger.warning("blocker_id %d not found for task %d", blocker_id, task.id)
            self._save(task)
            return task

    def get(self, task_id: int) -> Optional[Task]:
        return self.tasks.get(task_id)

    def list_tasks(self, user_id: str = "default") -> list[Task]:
        tasks = [t for t in self.tasks.values() if t.user_id == user_id or t.user_id == "default"]
        return sorted(tasks, key=lambda t: _PRIORITY_ORDER.get(t.priority, 1))

    async def update(self, task_id: int, **kwargs) -> Task:
        async with self._lock:
            return self._update_internal(task_id, **kwargs)

    def _update_internal(self, task_id: int, **kwargs) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if "blocked_by" in kwargs:
            self._sync_blocked_by(task, kwargs["blocked_by"])
        for k, v in kwargs.items():
            if k in _MUTABLE_FIELDS:
                setattr(task, k, v)
        task.updated_at = datetime.now().isoformat()
        if kwargs.get("status") == "in_progress" and not task.started_at:
            task.started_at = datetime.now().isoformat()
        if kwargs.get("status") == "completed":
            self._unlock_dependents(task)
        logger.info("Updated task %d: %s", task.id, kwargs)
        self._save(task)
        return task

    async def delete(self, task_id: int) -> bool:
        async with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return False
            for blocker_id in task.blocked_by:
                blocker = self.tasks.get(blocker_id)
                if blocker and task.id in blocker.blocks:
                    blocker.blocks.remove(task.id)
                    self._save(blocker)
            for child_id in task.blocks:
                child = self.tasks.get(child_id)
                if child and task.id in child.blocked_by:
                    child.blocked_by.remove(task.id)
                    self._save(child)
            del self.tasks[task_id]
            path = self.tasks_dir / f"task_{task_id}.json"
            path.unlink(missing_ok=True)
            logger.info("Deleted task %d", task_id)
            return True

    async def cancel(self, task_id: int, cascade: bool = True) -> Task:
        async with self._lock:
            visited: set[int] = set()
            return self._cancel_internal(task_id, cascade, visited)

    def _cancel_internal(self, task_id: int, cascade: bool, visited: set[int]) -> Task:
        if task_id in visited:
            return self.tasks[task_id]
        visited.add(task_id)
        task = self._update_internal(task_id, status="cancelled")
        if cascade:
            for child_id in task.blocks:
                child = self.tasks.get(child_id)
                if child and child.status not in ("completed", "cancelled"):
                    self._cancel_internal(child_id, cascade=True, visited=visited)
        return task

    def check_timeouts(self) -> list[Task]:
        now = datetime.now()
        timed_out = []
        for task in self.tasks.values():
            if task.status == "in_progress" and task.timeout and task.started_at:
                started = datetime.fromisoformat(task.started_at)
                if (now - started).total_seconds() > task.timeout:
                    timed_out.append(task)
        return timed_out

    def _unlock_dependents(self, completed_task: Task):
        for tid in list(completed_task.blocks):
            dependent = self.tasks.get(tid)
            if dependent and completed_task.id in dependent.blocked_by:
                dependent.blocked_by.remove(completed_task.id)
                self._save(dependent)

    def _sync_blocked_by(self, task: Task, new_blocked_by: list[int]):
        old_set = set(task.blocked_by)
        new_set = set(new_blocked_by)
        for removed_id in old_set - new_set:
            blocker = self.tasks.get(removed_id)
            if blocker and task.id in blocker.blocks:
                blocker.blocks.remove(task.id)
                self._save(blocker)
        for added_id in new_set - old_set:
            blocker = self.tasks.get(added_id)
            if blocker and task.id not in blocker.blocks:
                blocker.blocks.append(task.id)
                self._save(blocker)

    def _save(self, task: Task):
        path = self.tasks_dir / f"task_{task.id}.json"
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)


_task_manager: TaskManager | None = None


async def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
