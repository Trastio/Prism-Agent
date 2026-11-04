import re
from bs4 import BeautifulSoup
from src.scraper.selectors import Selectors


class ReviewParser:
    def parse_owner_name(self, card: BeautifulSoup) -> str:
        el = card.select_one(Selectors.OWNER_NAME)
        if el and el.text.strip():
            return el.text.strip()
        return ""

    def parse_model_name(self, card: BeautifulSoup) -> str:
        spec_el = card.select_one(Selectors.MODEL_FULL_NAME)
        series_el = card.select_one(Selectors.SERIES_NAME)
        parts = []
        if series_el and series_el.text.strip():
            parts.append(series_el.text.strip())
        if spec_el and spec_el.text.strip():
            parts.append(spec_el.text.strip())
        return " ".join(parts) if parts else ""

    def parse_purchase_date(self, card: BeautifulSoup) -> str | None:
        el = card.select_one(Selectors.PURCHASE_DATE)
        if el:
            text = el.get_text()
            match = re.search(r'(\d{4}[-\.]\d{1,2}[-\.]\d{1,2})', text)
            if match:
                return match.group(1)
            return el.text.strip()
        return None

    def parse_review_texts(self, card: BeautifulSoup) -> tuple[str, str]:
        best_text = ""
        worst_text = ""

        nice_block = card.select_one(Selectors.REVIEW_NICE_BLOCK)
        if nice_block:
            value_el = nice_block.select_one(Selectors.REVIEW_VALUE_IN_BLOCK)
            if value_el:
                best_text = value_el.get_text(strip=True)

        worce_block = card.select_one(Selectors.REVIEW_WORCE_BLOCK)
        if worce_block:
            value_el = worce_block.select_one(Selectors.REVIEW_VALUE_IN_BLOCK)
            if value_el:
                worst_text = value_el.get_text(strip=True)

        if not best_text and not worst_text:
            feeling = card.select_one(Selectors.REVIEW_FEELING)
            if feeling:
                text = feeling.get_text(strip=True)
                if "满意" in text and "不满意" in text:
                    idx = text.index("不满意")
                    best_text = text[:idx].replace("满意", "", 1).strip()
                    worst_text = text[idx:].replace("不满意", "", 1).strip()
                elif "满意" in text:
                    best_text = text.replace("满意", "", 1).strip()
                elif "不满意" in text:
                    worst_text = text.replace("不满意", "", 1).strip()

        return best_text, worst_text

    def _extract_review_id(self, card: BeautifulSoup, counter: int) -> str:
        link = card.select_one(Selectors.REVIEW_DETAIL_LINK)
        if link:
            href = link.get("href", "")
            match = re.search(r'/detail/view_([a-zA-Z0-9_]+)', href)
            if match:
                return f"k_{match.group(1)}"
            match = re.search(r'/detail/(\d+)', href)
            if match:
                return f"k_{match.group(1)}"
        return f"k_unknown_{counter}"

    def parse_review_score(self, card: BeautifulSoup) -> float | None:
        score_el = card.select_one(Selectors.REVIEW_SCORE)
        if score_el:
            try:
                return float(score_el.text.strip())
            except ValueError:
                pass
        return None

    def parse_review_dimensions(self, card: BeautifulSoup) -> dict[str, int]:
        dims = {}
        for li in card.select(Selectors.REVIEW_SCORE_ITEMS):
            score_el = li.select_one("p[class*='score']")
            name_el = li.select_one("p[class*='d_name']")
            if score_el and name_el:
                try:
                    dims[name_el.text.strip()] = int(score_el.text.strip())
                except ValueError:
                    pass
        return dims

    def parse_card(self, card: BeautifulSoup, counter: int) -> dict:
        best, worst = self.parse_review_texts(card)
        owner = self.parse_owner_name(card)
        if not owner.strip():
            owner = f"匿名车主_{counter}"

        result = {
            "review_id": self._extract_review_id(card, counter),
            "owner_id": owner,
            "model_full_name": self.parse_model_name(card),
            "purchase_date": self.parse_purchase_date(card),
            "best_review_text": best,
            "worst_review_text": worst,
        }

        score = self.parse_review_score(card)
        if score is not None:
            result["score"] = score

        dims = self.parse_review_dimensions(card)
        if dims:
            result["dimensions"] = dims

        return result

    def parse_review_list(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        list_el = soup.select_one(Selectors.REVIEW_LIST)
        if list_el:
            cards = list_el.select(Selectors.REVIEW_CARD)
        else:
            cards = soup.select(Selectors.REVIEW_CARD)
        return [self.parse_card(card, i) for i, card in enumerate(cards)]

    def parse_total_pages(self, html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        el = soup.select_one(Selectors.TOTAL_PAGES)
        if el:
            match = re.search(r'共(\d+)页', el.text)
            if match:
                return int(match.group(1))
        page_links = soup.select("a[href*='index_']")
        max_page = 1
        for a in page_links:
            match = re.search(r'index_(\d+)', a.get("href", ""))
            if match:
                max_page = max(max_page, int(match.group(1)))
        return max_page
