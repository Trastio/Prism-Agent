"""Tests for subject labeling (self/competitor/other) on AnalyzedPost.

See docs/superpowers/plans/2026-06-15-subject-tagging-and-event-quality.md
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import inspect, select

from models.schemas import AnalyzedPost, RawPost, Vehicle


# ── Task 1: schema 列 ──────────────────────────────────────────────────────

def test_analyzedpost_has_subject_column():
    """AnalyzedPost 模型必须有 subject 列属性（schema 改动生效）。

    sync attribute 检查，避开 pytest-asyncio 'could not get source code' 单跑问题。
    DB 层列创建由 create_all + init_db 迁移保证，运行时（T8）验证。
    """
    assert hasattr(AnalyzedPost, "subject"), "AnalyzedPost 必须有 subject 属性"
    assert AnalyzedPost.subject.nullable is True, "subject 应可为 NULL（兼容老数据）"


# ── Task 2: parse 提取 subject ──────────────────────────────────────────────

from pipeline.analysis.analyzer import AnalysisPipeline


def test_parse_response_extracts_subject():
    raw = '{"event_tags": [], "opinion_tags": [], "sentiment": "neutral", "dim_sentiment": {}, "confidence": 0.5, "subject": "competitor", "subject_name": "比亚迪海豚"}'
    result = AnalysisPipeline._parse_response(raw)
    assert result["subject"] == "competitor"
    assert result["subject_name"] == "比亚迪海豚"


def test_parse_response_defaults_subject_to_self():
    raw = '{"event_tags": [], "opinion_tags": [], "sentiment": "neutral", "dim_sentiment": {}, "confidence": 0.5}'
    result = AnalysisPipeline._parse_response(raw)
    assert result["subject"] == "self"
    assert result["subject_name"] == ""


def test_parse_event_response_extracts_subject():
    raw = '{"event_tags": [], "opinion_tags": [], "confidence": 0.5, "subject": "self"}'
    result = AnalysisPipeline._parse_event_response(raw)
    assert result["subject"] == "self"
