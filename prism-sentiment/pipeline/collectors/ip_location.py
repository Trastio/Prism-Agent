"""IP 属地归一化（英文 → 中文）——多采集器共享。

来源：OneAPI xhs V2 评论的 ip_location 是英文城市/省名（"Shanghai"/"Hainan"，
契约实测），TikHub xhs app_v2 评论同为英文省名（"Guangxi"）。V1 / 快手 / 抖音
评论是中文。归一化为中文与其他平台口径一致；未命中存原值（不做臆测）。
"""

from __future__ import annotations

IP_LOCATION_EN_CN = {
    # 直辖市
    "Beijing": "北京", "Shanghai": "上海", "Tianjin": "天津", "Chongqing": "重庆",
    # 华南/华东
    "Guangdong": "广东", "Guangzhou": "广东", "Shenzhen": "广东", "Guangxi": "广西",
    "Hainan": "海南", "Haikou": "海南", "Zhejiang": "浙江", "Hangzhou": "浙江",
    "Jiangsu": "江苏", "Nanjing": "江苏", "Suzhou": "江苏", "Wuxi": "江苏",
    "Fujian": "福建", "Xiamen": "福建", "Anhui": "安徽", "Jiangxi": "江西",
    "Shandong": "山东", "Qingdao": "山东", "Jinan": "山东",
    # 华中/华北
    "Hunan": "湖南", "Changsha": "湖南", "Hubei": "湖北", "Wuhan": "湖北",
    "Henan": "河南", "Zhengzhou": "河南", "Hebei": "河北", "Taiyuan": "山西",
    "Shanxi": "山西", "Inner Mongolia": "内蒙古", "Hohhot": "内蒙古",
    # 西南/西北
    "Sichuan": "四川", "Chengdu": "四川", "Yunnan": "云南", "Kunming": "云南",
    "Guizhou": "贵州", "Lhasa": "西藏", "Tibet": "西藏", "Shaanxi": "陕西",
    "Xi'an": "陕西", "Gansu": "甘肃", "Qinghai": "青海", "Ningxia": "宁夏",
    "Xinjiang": "新疆", "Urumqi": "新疆",
    # 东北
    "Liaoning": "辽宁", "Dalian": "辽宁", "Jilin": "吉林", "Harbin": "黑龙江",
    "Heilongjiang": "黑龙江", "Changchun": "吉林",
    # 港澳台/海外
    "Hong Kong": "香港", "Macao": "澳门", "Taiwan": "台湾",
    "Overseas": "海外",
}


def normalize_ip_location(loc) -> str:
    """英文属地 → 中文；中文/未命中原样返回（不做臆测）。"""
    s = str(loc or "").strip()
    if not s:
        return ""
    return IP_LOCATION_EN_CN.get(s, s)
