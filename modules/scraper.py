import xml.etree.ElementTree as ET
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
        titles, links = _parse_rss2(root, max_num)
    elif root_tag == "feed":
        titles, links = _parse_atom(root, max_num)
    elif root_tag == "RDF":
        titles, links = _parse_rdf(root, max_num)
    else:
        raise ValueError(f"Unknown feed root tag: {root.tag}")

    return ResultStructure(name=name, list_title=titles, list_link=links)


def _parse_rss2(root: ET.Element, max_num: int) -> tuple[list[str], list[str]]:
    titles, links = [], []
    for item in root.findall(".//item")[:max_num]:
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if title and link:
            titles.append(title)
            links.append(link)
    return titles, links


def _parse_atom(root: ET.Element, max_num: int) -> tuple[list[str], list[str]]:
    ns = "http://www.w3.org/2005/Atom"
    titles, links = [], []
    for entry in root.findall(f".//{{{ns}}}entry")[:max_num]:
        title_el = entry.find(f"{{{ns}}}title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link_el = entry.find(f"{{{ns}}}link")
        link = link_el.get("href", "").strip() if link_el is not None else ""
        if title and link:
            titles.append(title)
            links.append(link)
    return titles, links


def _parse_rdf(root: ET.Element, max_num: int) -> tuple[list[str], list[str]]:
    ns = "http://purl.org/rss/1.0/"
    titles, links = [], []
    for item in root.findall(f"{{{ns}}}item")[:max_num]:
        title = _child_text(item, f"{{{ns}}}title")
        link = _child_text(item, f"{{{ns}}}link")
        if title and link:
            titles.append(title)
            links.append(link)
    return titles, links


def _child_text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _scrape_html(name: str, site: SiteStructure, max_num: int) -> ResultStructure:
    r = requests.get(site.news_home, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    soup = bs(r.text, "lxml")
    titles = [site.get_title(x) for x in soup.select(site.scrape_title)]
    links = [_resolve_link(site, x) for x in soup.select(site.scrape_link)]

    # 見出しとサムネイルが同じ記事へ二重にリンクしているサイトがあるため、
    # 空タイトルと重複リンクを落としてから max_num 件に切る
    # (先に切ると使えない要素で枠が埋まってしまう)
    list_title, list_link, seen = [], [], set()
    for title, link in zip(titles, links):
        if not title or not link or link in seen:
            continue
        seen.add(link)
        list_title.append(title)
        list_link.append(link)
        if len(list_link) == max_num:
            break

    return ResultStructure(name=name, list_link=list_link, list_title=list_title)


def _resolve_link(site: SiteStructure, el) -> str:
    # 相対 href を返すサイトがあるので news_home 基準で絶対 URL にする。
    # 絶対 URL はそのまま返るため prefix_home 方式のサイトへの影響はない。
    href = f"{site.prefix_home}{site.get_link(el)}"
    return urljoin(site.news_home, href) if href else ""
