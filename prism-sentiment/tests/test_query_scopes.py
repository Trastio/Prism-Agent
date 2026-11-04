"""Tests: 统一查询构造器 scoped_posts + time_window_filter（Phase 3 T3.2/T3.4）。"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, func

from api.query_scopes import scoped_posts, time_window_filter
from models.schemas import RawPost, LISTING_CALIBER, SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY


def test_scoped_posts_default_caliber():
    """scoped_posts 默认挂 LISTING_CALIBER 口径。"""
    stmt = scoped_posts("v-test")
    # 编译 SQL 检查含口径条件（subject/author_type/analysis_status）
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "vehicle_id" in sql
    # LISTING_CALIBER 三条件都应出现（subject=self / author_type 排除 / analysis_status!=irrelevant）
    assert "irrelevant" in sql  # RELEVANT_ONLY


def test_scoped_posts_with_time_window():
    """scoped_posts 带 start/end 时间窗用 coalesce。"""
    stmt = scoped_posts("v-test", start="2026-10-01", end="2026-10-06")
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "coalesce" in sql.lower()  # coalesce(published_at, collected_at)
    assert "2026-10-01" in sql


def test_scoped_posts_custom_caliber():
    """scoped_posts 支持自定义 caliber（如仅 RELEVANT_ONLY）。"""
    stmt = scoped_posts("v-test", caliber=(RELEVANT_ONLY,))
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "irrelevant" in sql


def test_time_window_filter_coalesce():
    """time_window_filter 返回 coalesce 条件列表。"""
    conds = time_window_filter(start="2026-10-01", end="2026-10-06")
    assert len(conds) == 2  # start + end
    # 编译检查含 coalesce
    sql = str(select(RawPost).where(*conds).compile(compile_kwargs={"literal_binds": True}))
    assert "coalesce" in sql.lower()


def test_time_window_filter_partial():
    """time_window_filter 只传 start 返回 1 条件。"""
    conds = time_window_filter(start="2026-10-01")
    assert len(conds) == 1


def test_time_window_filter_none():
    """time_window_filter 无参数返回空列表。"""
    conds = time_window_filter()
    assert conds == []
