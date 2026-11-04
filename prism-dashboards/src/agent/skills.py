from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    tags: list[str]
    body: str
    path: Path


class SkillLoader:
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self._scan()

    def _scan(self):
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return
        for skill_file in self.skills_dir.glob("*/SKILL.md"):
            try:
                skill = self._parse(skill_file)
                self.skills[skill.name] = skill
                logger.info(f"Loaded skill: {skill.name}")
            except Exception as e:
                logger.warning(f"Failed to parse {skill_file}: {e}")

    def _parse(self, path: Path) -> Skill:
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if not match:
            raise ValueError(f"Invalid skill file format: {path}")
        meta = yaml.safe_load(match.group(1))
        body = match.group(2).strip()
        return Skill(
            name=meta["name"],
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            body=body,
            path=path,
        )

    def get_descriptions(self) -> list[dict]:
        return [{"name": s.name, "description": s.description} for s in self.skills.values()]

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if skill is None:
            available = ", ".join(sorted(self.skills.keys()))
            return f"错误：未知技能 '{name}'。可用技能：{available}"
        return skill.body


_global_skill_loader: SkillLoader | None = None


def get_skill_loader() -> SkillLoader:
    global _global_skill_loader
    if _global_skill_loader is None:
        _global_skill_loader = SkillLoader()
    return _global_skill_loader
