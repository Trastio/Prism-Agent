import json
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sqlalchemy.dialects.sqlite import insert
from src.storage.db import session_scope
from src.models.orm import Conversation, UserPreference
from src.agent.prompts import UNIFIED_SYSTEM_PROMPT


@dataclass
class PreferenceDTO:
    user_id: str = "default"
    budget_max: int | None = None
    budget_min: int | None = None
    segments: list = field(default_factory=list)
    energy_types: list = field(default_factory=list)
    dimension_weights: dict = field(default_factory=lambda: {"续航": 0.2, "安全": 0.2, "舒适": 0.2, "颜值": 0.2, "性价比": 0.2})

logger = logging.getLogger(__name__)

MAX_MESSAGES = 40
DEFAULT_USER = "default"


class SessionManager:
    def create_session(self, user_id: str = DEFAULT_USER) -> tuple[str, list]:
        session_id = str(uuid.uuid4())[:8]
        system_prompt = UNIFIED_SYSTEM_PROMPT
        pref = self.get_preference(user_id)
        prompt_with_prefs = self._inject_preferences(system_prompt, pref)
        initial_msgs = [{"role": "system", "content": prompt_with_prefs}]
        with session_scope() as session:
            conv = Conversation(session_id=session_id, user_id=user_id)
            conv.set_messages(initial_msgs)
            session.add(conv)
        return session_id, initial_msgs

    def resume_session(self, session_id: str) -> list | None:
        with session_scope() as session:
            conv = session.query(Conversation).filter_by(session_id=session_id).first()
            if conv is None or conv.is_expired:
                return None
            conv.last_active_at = datetime.now(timezone.utc)
            msgs = conv.messages_list
        return msgs

    def save_messages(self, session_id: str, messages: list):
        with session_scope() as session:
            conv = session.query(Conversation).filter_by(session_id=session_id).first()
            if conv:
                truncated = self._truncate_context(messages)
                conv.set_messages(truncated)

    def get_preference(self, user_id: str) -> PreferenceDTO:
        with session_scope() as session:
            pref = session.query(UserPreference).filter_by(user_id=user_id).first()
            if pref is None:
                pref = UserPreference(user_id=user_id)
                session.add(pref)
                session.flush()
            return PreferenceDTO(
                user_id=pref.user_id,
                budget_max=pref.budget_max,
                budget_min=pref.budget_min,
                segments=pref.segments or [],
                energy_types=pref.energy_types or [],
                dimension_weights=pref.dimension_weights_dict,
            )

    def update_preference(self, user_id: str, **kwargs):
        if "dimension_weights" in kwargs and kwargs["dimension_weights"]:
            weights = kwargs["dimension_weights"]
            total = sum(weights.values())
            if total == 0:
                return  # 全为零，无法归一化
            if abs(total - 1.0) > 0.001:
                kwargs["dimension_weights"] = {k: v / total for k, v in weights.items()}
        with session_scope() as session:
            stmt = insert(UserPreference).values(user_id=user_id, **kwargs)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={k: v for k, v in kwargs.items() if v is not None},
            )
            session.execute(stmt)

    def _inject_preferences(self, prompt: str, pref: PreferenceDTO) -> str:
        parts = [prompt]
        if pref.budget_max:
            parts.append(f"\n用户偏好：预算 {pref.budget_min or 0}-{pref.budget_max} 元")
        if pref.segments:
            parts.append(f"车型偏好：{', '.join(pref.segments)}")
        if pref.energy_types:
            parts.append(f"能源偏好：{', '.join(pref.energy_types)}")
        weights = pref.dimension_weights
        if weights:
            sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)
            parts.append(f"评价权重：{' > '.join(f'{k}({v:.0%})' for k, v in sorted_weights)}")
        return "\n".join(parts)

    def cleanup_expired_sessions(self) -> int:
        """Delete expired conversations. Returns count of deleted records."""
        from datetime import datetime, timedelta, timezone
        with session_scope() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            from src.models.orm import Conversation
            count = session.query(Conversation).filter(
                Conversation.last_active_at < cutoff
            ).delete()
        return count

    def _truncate_context(self, messages: list) -> list:
        if len(messages) <= MAX_MESSAGES:
            return messages
        system_msgs = [m for m in messages if m["role"] == "system"]
        non_system = messages[len(system_msgs):]
        keep_count = MAX_MESSAGES - len(system_msgs)
        idx = max(0, len(non_system) - keep_count)
        while idx > 0 and non_system[idx]["role"] == "tool":
            idx -= 1
        if idx > 0 and non_system[idx - 1].get("role") == "assistant" and non_system[idx - 1].get("tool_calls"):
            idx -= 1
        idx = max(0, idx)
        recent = non_system[idx:]
        if len(recent) > keep_count:
            cut = len(recent) - keep_count
            while cut > 0 and recent[cut]["role"] == "tool":
                cut -= 1
            if cut > 0 and recent[cut - 1].get("role") == "assistant" and recent[cut - 1].get("tool_calls"):
                cut -= 1
            cut = max(0, cut)
            recent = recent[cut:]
        return system_msgs + recent


# Shared singleton — used by chat routes and periodic cleanup
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
