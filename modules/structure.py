from typing import Callable, Optional
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SiteStructure:
    source: str  # "html" or "rss"
    news_home: str
    # HTML scraping fields
    prefix_home: str = ""
    scrape_title: str = ""
    get_title: Optional[Callable] = None
    scrape_link: str = ""
    get_link: Optional[Callable] = None
    # RSS field
    rss_url: str = ""


@dataclass(frozen=True)
class ResultStructure:
    name: str
    list_title: list[str]
    list_link: list[str]
    # 掲載日 ("M/D")。取得できない記事は空文字。list_title と同じ長さ
    list_date: list[str] = field(default_factory=list)

    @property
    def dict_title_link(self) -> dict[str, str]:
        return {k: v for k, v in zip(self.list_title, self.list_link)}

    def is_empty(self) -> bool:
        return len(self.list_title) == 0 or len(self.list_link) == 0
