from pipeline.collectors.post_utils import strip_html

def test_strip_anchor_tag():
    assert strip_html('<a href="https://m.weibo.cn/...">超话</a>') == "超话"

def test_strip_multiple_tags():
    assert strip_html('<b>风云T7</b> <a href="x">上市</a>') == "风云T7 上市"

def test_no_html_unchanged():
    assert strip_html("风云T7 上市评测") == "风云T7 上市评测"

def test_empty_string():
    assert strip_html("") == ""

def test_none_input():
    assert strip_html(None) is None
