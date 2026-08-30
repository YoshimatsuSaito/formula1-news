import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup as bs

from .structure import SiteStructure, ResultStructure

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_JST = timezone(timedelta(hours=9))


def scrape_news(
    name: str, site_structure: SiteStructure, max_num: int = 10
) -> ResultStructure:
    if site_structure.source == "rss":
        return _scrape_rss(name, site_structure, max_num)
    return _scrape_html(name, site_structure, max_num)


def _scrape_rss(name: str, site: SiteStructure, max_num: int) -> ResultStructure:
    r = requests.get(
        site.rss_url,
        headers={**_HEADERS, "Accept": "application/rss+xml, application/atom+xml, */*"},
        timeout=15,
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)

    # strip namespace from root tag for format detection
    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    if root_tag == "rss":
        titles, links, dates = _parse_rss2(root, max_num)
    elif root_tag == "feed":
        titles, links, dates = _parse_atom(root, max_num)
    elif root_tag == "RDF":
        titles, links, dates = _parse_rdf(root, max_num)
    else:
        raise ValueError(f"Unknown feed root tag: {root.tag}")

    return ResultStructure(
        name=name, list_title=titles, list_link=links, list_date=dates
    )


_Parsed = tuple[list[str], list[str], list[str]]

# dc:date は RSS1.0(RDF) が配信日時に使う
_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


def _parse_rss2(root: ET.Element, max_num: int) -> _Parsed:
    titles, links, dates = [], [], []
    for item in root.findall(".//item")[:max_num]:
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if title and link:
            titles.append(title)
            links.append(link)
            dates.append(
                _fmt_date(_child_text(item, "pubDate") or _child_text(item, _DC_DATE))
            )
    return titles, links, dates


def _parse_atom(root: ET.Element, max_num: int) -> _Parsed:
    ns = "http://www.w3.org/2005/Atom"
    titles, links, dates = [], [], []
    for entry in root.findall(f".//{{{ns}}}entry")[:max_num]:
        title_el = entry.find(f"{{{ns}}}title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link_el = entry.find(f"{{{ns}}}link")
        link = link_el.get("href", "").strip() if link_el is not None else ""
        if title and link:
            titles.append(title)
            links.append(link)
            dates.append(
                _fmt_date(
                    _child_text(entry, f"{{{ns}}}published")
                    or _child_text(entry, f"{{{ns}}}updated")
                )
            )
    return titles, links, dates


def _parse_rdf(root: ET.Element, max_num: int) -> _Parsed:
    ns = "http://purl.org/rss/1.0/"
    titles, links, dates = [], [], []
    for item in root.findall(f"{{{ns}}}item")[:max_num]:
        title = _child_text(item, f"{{{ns}}}title")
        link = _child_text(item, f"{{{ns}}}link")
        if title and link:
            titles.append(title)
            links.append(link)
            dates.append(_fmt_date(_child_text(item, _DC_DATE)))
    return titles, links, dates


def _child_text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _fmt_date(raw: str) -> str:
    """配信日時を JST の "M/D" に整形する。解釈できなければ空文字。

    Atom / dc:date は ISO8601、RSS2 の pubDate は RFC822 と形式が違うので
    両方試す。表示は日付だけにして、どのソースでも同じ見え方に揃える。
    """
    raw = (raw or "").strip()
    if not raw:
        return ""

    dt = None
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            dt = parse(raw)
            break
        except (TypeError, ValueError):
            continue
    if dt is None:
        return ""

    # タイムゾーンの無い日時は UTC とみなす（JST に寄せると未来日付になりうる）
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_JST).strftime("%-m/%-d")


def _scrape_html(name: str, site: SiteStructure, max_num: int) -> ResultStructure:
    r = requests.get(site.news_home, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    soup = bs(_markup(r), "lxml")
    titles = [site.get_title(x) for x in soup.select(site.scrape_title)]
    link_els = soup.select(site.scrape_link)
    links = [_resolve_link(site, x) for x in link_els]
    raw_dates = [_html_date(x) for x in link_els]

    # 見出しとサムネイルが同じ記事へ二重にリンクしているサイトがあるため、
    # 空タイトルと重複リンクを落としてから max_num 件に切る
    # (先に切ると使えない要素で枠が埋まってしまう)
    list_title, list_link, picked_dates, seen = [], [], [], set()
    for title, link, raw in zip(titles, links, raw_dates):
        if not title or not link or link in seen:
            continue
        seen.add(link)
        list_title.append(title)
        list_link.append(link)
        picked_dates.append(raw)
        if len(list_link) == max_num:
            break

    return ResultStructure(
        name=name,
        list_link=list_link,
        list_title=list_title,
        list_date=_dates_from_raw(picked_dates),
    )


def _html_date(el) -> str:
    """記事リンクの近くにある ``<time datetime="...">`` の生の値を返す。

    一覧ページの多くは日付を time 要素で持っており、datetime 属性なら
    サイトごとに表示書式を解釈しなくても機械可読な値が取れる。
    リンク自身から2階層上まで（概ね ``<a>`` → ``<h2>`` → ``<li>``）を見る。
    それ以上遡ると一覧全体に届いてしまい、隣の記事の日付を拾いかねない。
    """
    node = el
    for _ in range(3):
        if node is None:
            break
        found = node.find("time", attrs={"datetime": True})
        if found:
            return found["datetime"]
        node = node.parent
    return ""


def _dates_from_raw(raw_dates: list[str]) -> list[str]:
    # 全記事がまったく同じ日時を指す場合、記事ごとの time 要素ではなく
    # 一覧全体で共有された要素を拾っている可能性が高いので日付は出さない。
    # (同じ日の記事が並ぶことはあるが、秒まで一致することはまず無い)
    filled = [d for d in raw_dates if d]
    if len(filled) > 2 and len(set(filled)) == 1:
        return ["" for _ in raw_dates]
    return [_fmt_date(d) for d in raw_dates]


def _markup(r: requests.Response) -> str | bytes:
    # HTTP ヘッダに charset が無いと requests は ISO-8859-1 と決め打ちする。
    # 旧来の携帯向けサイトは Shift_JIS を meta タグでしか宣言しないので、
    # r.text を使うと日本語の見出しが丸ごと文字化けする。
    # 宣言が無いときはバイト列のまま渡し、meta charset の解釈を bs4 に任せる。
    if "charset=" in r.headers.get("Content-Type", "").lower():
        return r.text
    return r.content


def _resolve_link(site: SiteStructure, el) -> str:
    # 相対 href を返すサイトがあるので news_home 基準で絶対 URL にする。
    # 絶対 URL はそのまま返るため prefix_home 方式のサイトへの影響はない。
    href = f"{site.prefix_home}{site.get_link(el)}"
    return urljoin(site.news_home, href) if href else ""
