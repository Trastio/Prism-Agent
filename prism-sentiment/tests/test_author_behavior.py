"""作者行为背调（B1）——历史帖汽车内容占比判定营销号。

库内历史帖跨车型合计：≥3 帖且 ≥70% 含汽车营销信号词→marketing_account。
"""
import pytest
from pipeline.collectors.post_utils import profile_author_behavior


def test_marketing_account_detected():
    """≥3帖且≥70%汽车内容→marketing_account"""
    posts = [{"title": "风云T7试驾评测", "content": "试驾..."},
             {"title": "上市价格分析", "content": "价格..."},
             {"title": "配置对比", "content": "配置..."}]
    assert profile_author_behavior("车评人小王", posts) == "marketing_account"


def test_real_owner_not_flagged():
    """<3帖不标记"""
    posts = [{"title": "我的风云T7", "content": "提车了"}]
    assert profile_author_behavior("张三", posts) is None


def test_threshold_boundary():
    """3帖边界：2汽车+1非汽车=67%<70%不标记"""
    posts = [{"title": "试驾", "content": ""}, {"title": "评测", "content": ""},
             {"title": "今天天气", "content": ""}]
    assert profile_author_behavior("边界用户", posts) is None


def test_cross_vehicle_marketing():
    """跨车型合计：风云T7 2帖 + 星愿 2帖 = 4帖全汽车→标记"""
    posts = [{"title": "风云T7试驾", "content": ""}, {"title": "风云T7评测", "content": ""},
             {"title": "星愿试驾", "content": ""}, {"title": "星愿评测", "content": ""}]
    assert profile_author_behavior("跨车营销号", posts) == "marketing_account"
