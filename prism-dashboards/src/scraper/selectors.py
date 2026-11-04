class Selectors:
    """汽车之家口碑页面 DOM 选择器映射。页面结构变更时只需修改此文件。

    2025年口碑页面改版为 Next.js SPA，class 名带 hash 后缀。
    使用属性选择器 [class*='xxx'] 匹配部分 class 名，避免 hash 变更导致失效。
    """

    REVIEW_LIST = "ul[class*='list_list_con']"
    REVIEW_CARD = "li.clearfix"
    OWNER_NAME = "div[class*='list_msg'] span"
    MODEL_FULL_NAME = "span[class*='list_spec']"
    SERIES_NAME = "span[class*='list_series']"
    PURCHASE_DATE = "p[class*='list_timeline']"
    REVIEW_TITLE = "h1[class*='list_kb_title'] a"
    REVIEW_DETAIL_LINK = "a[href*='k.autohome.com.cn/detail']"
    REVIEW_NICE_BLOCK = "div[class*='list_nice']:not([class*='key']):not([class*='value'])"
    REVIEW_WORCE_BLOCK = "div[class*='list_worce']:not([class*='key']):not([class*='value'])"
    REVIEW_VALUE_IN_BLOCK = "div[class*='list_nice_value']"
    REVIEW_FEELING = "div[class*='list_feeling']"
    REVIEW_SCORE = "div[class*='list_custom_rank'] span"
    REVIEW_SCORE_ITEMS = "ul[class*='list_dimension_score'] li"
    NEXT_PAGE = "a[class*='page-item-next']"
    TOTAL_PAGES = "span[class*='page-item-info']"
    SEARCH_RESULTS = "a.search-result-item"
