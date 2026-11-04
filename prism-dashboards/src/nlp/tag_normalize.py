"""标签归一映射：碎片标签 → 封闭标签。

关系：封闭表（L2_TAG_MAP）定义合法标签，本表定义碎片→合法的映射。
映射表目标必须在封闭表内。随封闭表同步更新。
"""
from src.nlp.tagger import L2_TAG_MAP

_FRAGMENT_MAP = {
    "智能化": {
        "车机卡顿": "车机问题", "车机黑屏": "车机问题", "车机难用": "车机问题",
        "车机差": "车机问题", "车机一般": "车机问题", "车机反应慢": "车机问题",
        "车机软件差": "车机问题", "车机操作复杂": "车机问题", "车机网络差": "车机问题",
        "车机功能少": "车机问题", "车机功能不足": "车机问题", "车机应用少": "车机问题",
        "车机不足": "车机问题", "车机待优化": "车机问题", "车机需优化": "车机问题",
        "车机有BUG": "车机问题", "车机故障": "车机问题", "车机导航差": "车机问题",
        "车机逻辑差": "车机问题", "车机生态不足": "车机问题",
        "OTA升级慢": "OTA问题", "OTA慢": "OTA问题", "OTA更新慢": "OTA问题",
        "OTA未推送": "OTA问题", "OTA滞后": "OTA问题", "系统升级慢": "OTA问题",
        "系统更新慢": "OTA问题", "智驾更新慢": "OTA问题", "升级慢": "OTA问题",
        "语音不好用": "语音问题", "语音识别差": "语音问题", "语音识别不准": "语音问题",
        "语音不灵敏": "语音问题", "语音助手差": "语音问题", "语音响应慢": "语音问题",
        "语音延迟": "语音问题", "语音笨拙": "语音问题", "语音误唤醒": "语音问题",
        "语音反应慢": "语音问题", "语音识别延迟": "语音问题",
        "辅助驾驶不足": "辅助驾驶差", "辅助驾驶保守": "辅助驾驶差",
        "辅助驾驶待升级": "辅助驾驶差", "辅助驾驶待提升": "辅助驾驶差",
        "辅助驾驶需优化": "辅助驾驶差", "智驾待优化": "辅助驾驶差",
        "智驾待完善": "辅助驾驶差", "智驾待提升": "辅助驾驶差",
    },
    "舒适": {
        "风噪大": "噪音大", "风噪明显": "噪音大", "胎噪大": "噪音大",
        "座椅偏硬": "座椅不舒适", "座椅硬": "座椅不舒适", "座椅不适": "座椅不舒适",
    },
    "续航": {
        "充电麻烦": "充电不便", "无线充电慢": "充电慢",
    },
    "内饰": {
        "新车异味": "异味大", "异味": "异味大", "异味重": "异味大", "内饰异味": "异味大",
    },
    "外观": {
        "外观不好看": "外观普通", "造型普通": "外观普通",
    },
    "性价比": {
        "划算": "价格实惠",
    },
}

_VALID_NAMES = set()
_VALID_PAIRS = set()
for _cat, _tags in L2_TAG_MAP.items():
    for _senti in ("pro", "con"):
        for _name in _tags.get(_senti, []):
            _VALID_NAMES.add(_name)
            _VALID_PAIRS.add((_name, _senti))

_FRAGMENT_TARGETS = set()
for _cat_map in _FRAGMENT_MAP.values():
    _FRAGMENT_TARGETS.update(_cat_map.values())
assert _FRAGMENT_TARGETS <= _VALID_NAMES, f"映射表目标不在封闭表: {_FRAGMENT_TARGETS - _VALID_NAMES}"


def normalize_tag(tag_name: str, tag_category: str) -> str:
    """碎片标签归一到封闭标签；封闭标签原样返回；未知标签原样返回。"""
    if tag_name in _VALID_NAMES:
        return tag_name
    return _FRAGMENT_MAP.get(tag_category, {}).get(tag_name, tag_name)


def get_valid_pairs() -> set:
    return set(_VALID_PAIRS)


def get_valid_names() -> set:
    return set(_VALID_NAMES)
