"""ソースの一覧ページを取得し、記事リンク周辺の HTML を出力する診断ツール。

掲載日がページのどこに書かれているかを調べるために使う。
開発環境から対象サイトへ到達できないことがあるため、GitHub Actions 上で
実行して実際の HTML をログで確認できるようにしてある。

    python tools/inspect_source.py "F1速報,TopNews"
    python tools/inspect_source.py "F1-Gate" "article.fv-sub a|a:has(h3)"

HTML ソースは記事リンク周辺の構造を、RSS ソースはフィードの取得可否と
中身の件数を出す。
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup as bs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.load_config import load_config  # noqa: E402
from modules.scraper import (  # noqa: E402
    _HEADERS,
    _HEADING_LOOKBACK,
    _heading_date,
    _html_date,
    _html_text_date,
    _markup,
    _parse_heading_date,
    scrape_news,
)

_ANCESTORS = 3      # 記事リンクから何階層上まで見るか
_SNIPPET = 700      # 1要素あたりに出す HTML の長さ
_ARTICLES = 3       # 何記事ぶん出すか
_ARTICLES_DATE = 4  # 掲載日の出どころを何記事ぶん出すか


def _probe(url: str, accept: str | None = None) -> requests.Response | None:
    """URL を叩いてステータスだけ出す。到達性の切り分けに使う。"""
    headers = dict(_HEADERS)
    if accept:
        headers["Accept"] = accept
    try:
        r = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        print(f"  {url}\n    ERROR {type(e).__name__}: {e}")
        return None
    print(f"  {url}\n    HTTP {r.status_code} / {r.headers.get('Content-Type')} / {len(r.content)} bytes")
    return r


def _inspect_rss(site) -> None:
    """フィードが取れるか、どの形式で何件入っているかを見る。"""
    print(f"feed: {site.rss_url}")
    r = requests.get(
        site.rss_url,
        headers={**_HEADERS, "Accept": "application/rss+xml, application/atom+xml, */*"},
        timeout=20,
    )
    print(f"HTTP {r.status_code} / {r.headers.get('Content-Type')} / {len(r.content)} bytes")
    if r.status_code != 200:
        # 拒否されている場合は本文に理由が書かれていることがある
        print("\n本文の先頭:")
        print("  " + " ".join(r.text[:500].split()))
        # フィードだけの問題か、サイト全体が拒否しているのかを見る。
        # 一覧ページが取れるなら HTML スクレイピングへ切り替える道がある
        print("\n同じサイトの他のパス:")
        _FEED = "application/rss+xml, application/atom+xml, */*"
        _probe(site.news_home)
        _probe(site.news_home.rstrip("/") + "/feed", _FEED)
        root = "/".join(site.news_home.split("/")[:3])
        _probe(root)
        return

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        print(f"\nXML として解釈できない: {e}")
        print("  " + " ".join(r.text[:500].split()))
        return

    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    print(f"\nroot タグ: {tag}")
    # 形式ごとに記事要素の数を数える
    for label, path in [
        ("RSS2 item", ".//item"),
        ("Atom entry", ".//{http://www.w3.org/2005/Atom}entry"),
        ("RDF item", ".//{http://purl.org/rss/1.0/}item"),
    ]:
        found = root.findall(path)
        if found:
            print(f"{label}: {len(found)}件")
            print("  先頭の中身:")
            print("    " + " ".join(ET.tostring(found[0], encoding="unicode")[:600].split()))


def _survey(soup) -> None:
    """セレクタが一致しないときに、組み直すための材料を出す。"""
    print("\n--- 構造の調査 ---")

    # 見出しに使われているタグとクラス。記事タイトルは見出しに入っていることが多い
    print("\n見出し要素:")
    for tag in ("h1", "h2", "h3", "h4"):
        found = soup.find_all(tag)
        if not found:
            continue
        classes = Counter(" ".join(h.get("class") or []) for h in found)
        print(f"  <{tag}> {len(found)}個  class={dict(classes)}")
        for h in found[:2]:
            print(f"      {' '.join(str(h).split())[:240]}")
            # 見出しを包んでいる要素。記事カードの構造が分かる
            node, depth = h.parent, 1
            while node is not None and depth <= 3:
                label = f"<{node.name}"
                if node.get("class"):
                    label += f" class={' '.join(node['class'])}"
                if node.name == "a":
                    label += f" href={node.get('href')}"
                print(f"        祖先[{depth}] {label}>")
                node, depth = node.parent, depth + 1

    # <time> の周辺に記事リンクがあるはずなので、その祖先をたどる
    times = soup.find_all("time")
    if times:
        print("\n<time> の祖先と、その中のリンク:")
        for t in times[:2]:
            node, depth = t.parent, 1
            while node is not None and depth <= 4:
                label = f"<{node.name}"
                if node.get("class"):
                    label += f" class={' '.join(node['class'])}"
                if node.get("id"):
                    label += f" id={node['id']}"
                links = node.find_all("a", href=True)
                print(f"  [{depth}] {label}>  リンク{len(links)}個")
                for a in links[:3]:
                    print(f"        {a.get('href')[:90]}  {a.get_text(' ', strip=True)[:50]!r}")
                node, depth = node.parent, depth + 1
            print()

    # 記事リンクがどの入れ物に、いくつ入っているか。
    # 一覧がページ内のどこにあるかを一望できる
    print("\nリンクの置き場所 (祖先3階層ごとの件数):")
    places: dict[str, list] = {}
    for a in soup.find_all("a", href=True):
        chain, node, depth = [], a.parent, 0
        while node is not None and depth < 3:
            label = node.name
            if node.get("class"):
                label += "." + ".".join(node["class"])
            chain.append(label)
            node, depth = node.parent, depth + 1
        places.setdefault(" < ".join(chain), []).append(a)
    for sig, links in sorted(places.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"  {len(links):4d}  {sig}")
        print(f"        例: {links[0].get('href')[:80]}  {links[0].get_text(' ', strip=True)[:40]!r}")

    # href のパターン。記事 URL の形を掴む
    print("\nhref のパターン上位:")
    pats = Counter()
    for a in soup.find_all("a", href=True):
        # 末尾のスラッグを畳んで形だけ残す
        pat = re.sub(r"[^/]{4,}", "*", urlparse(a["href"]).path)
        pats[pat] += 1
    for pat, n in pats.most_common(12):
        print(f"  {n:4d}  {pat}")


def dry_run(name: str, site, selector: str) -> None:
    """候補セレクタで実際のスクレイパを走らせ、出来上がる記事一覧を見る。

    件数だけでなく掲載日まで取れるかを、本番と同じコードで確かめる。
    セレクタに "|" が使えないので、タイトル側と リンク側は ">>" で区切る
    (省略時は同じセレクタを両方に使う)。
    """
    title_sel, _, link_sel = selector.partition(">>")
    candidate = replace(
        site,
        scrape_title=title_sel.strip(),
        scrape_link=(link_sel.strip() or title_sel.strip()),
    )
    print(f"\n  title={candidate.scrape_title!r} link={candidate.scrape_link!r}")
    try:
        result = scrape_news(name=name, site_structure=candidate)
    except Exception as e:
        print(f"    FAIL {type(e).__name__}: {e}")
        return
    print(f"    {len(result.list_title)}件 / 掲載日あり {sum(1 for d in result.list_date if d)}件")
    for t, l, d in zip(result.list_title, result.list_link, result.list_date):
        print(f"      [{d or '----------'}] {t[:52]}")
        print(f"                   {l[:95]}")


def date_trace(site, soup) -> None:
    """記事ごとに、掲載日をどこから読んだのかを並べる。

    掲載日の補完は time 要素 → 周辺テキスト → 直前の見出し の順に試すので、
    どの段で何を拾ったかが分からないと誤った日付の出どころを追えない。
    """
    print("\n--- 掲載日の出どころ ---")
    els, seen = [], set()
    for el in soup.select(site.scrape_link):
        link = el.get("href")
        if link and link not in seen:
            seen.add(link)
            els.append(el)

    for el in els[:_ARTICLES_DATE]:
        print(f"\n  記事: {el.get_text(' ', strip=True)[:50]}")
        print(f"    time要素      : {_html_date(el)!r}")
        print(f"    周辺テキスト  : {_html_text_date(el)!r}")
        print(f"    直前の見出し  : {_heading_date(el)!r}")
        # _heading_date が実際に見ている見出しを、同じ順で出す
        heads = el.find_all_previous(
            ["h1", "h2", "h3", "h4", "h5", "h6"], limit=_HEADING_LOOKBACK
        )
        for h in heads:
            text = h.get_text(" ", strip=True)
            parsed = _parse_heading_date(text)
            mark = "  ★一致" if parsed else ""
            print(f"      <{h.name}> {text[:46]!r} -> {parsed}{mark}")


def try_selectors(soup, selectors: list[str]) -> None:
    """セレクタ候補を当ててみて、件数と中身を出す。

    config を書き換えずに候補を比べられるようにしてある。
    """
    print("\n--- セレクタ候補 ---")
    for sel in selectors:
        try:
            found = soup.select(sel)
        except Exception as e:
            print(f"\n  {sel!r}: 不正なセレクタ ({e})")
            continue
        print(f"\n  {sel!r}: {len(found)}個")
        for el in found[:4]:
            href = el.get("href") if el.name == "a" else None
            print(f"      {el.get_text(' ', strip=True)[:60]!r}")
            if href:
                print(f"        href={href[:100]}")


def inspect(name: str, site, selectors: list[str] | None = None) -> None:
    print(f"\n{'=' * 72}")
    print(f"{name}  ({site.source})  {site.news_home}")
    print("=" * 72)

    if site.source == "rss":
        _inspect_rss(site)
        return

    r = requests.get(site.news_home, headers=_HEADERS, timeout=20)
    print(f"HTTP {r.status_code} / {r.headers.get('Content-Type')} / {len(r.content)} bytes")
    r.raise_for_status()
    soup = bs(_markup(r), "lxml")

    # まず time 要素の有無。これがあれば既存の実装で拾えるはず
    times = soup.find_all("time")
    with_attr = [t for t in times if t.has_attr("datetime")]
    print(f"\n<time> 要素: {len(times)}個 (datetime属性あり: {len(with_attr)}個)")
    for t in times[:3]:
        print(f"    {str(t)[:160]}")

    els = soup.select(site.scrape_link)
    print(f"\n記事リンク ({site.scrape_link}): {len(els)}個")

    if els:
        date_trace(site, soup)

    if selectors:
        try_selectors(soup, selectors)
        print("\n--- 候補セレクタで実際に取得してみる ---")
        for sel in selectors:
            dry_run(name, site, sel)

    # セレクタが当たらない = ページ構造が変わった。
    # 新しいセレクタを決めるための材料を出す。候補を渡したときは
    # その結果を読みたいので、長い調査結果は出さない
    if not els and not selectors:
        _survey(soup)
        return

    for el in els[:_ARTICLES]:
        print(f"\n{'-' * 72}")
        print(f"記事: {el.get_text(' ', strip=True)[:60]}")
        node, depth = el, 0
        while node is not None and depth <= _ANCESTORS:
            html = " ".join(str(node).split())
            label = f"[{depth}] <{node.name}"
            if node.get("class"):
                label += f" class={' '.join(node['class'])[:60]}"
            print(f"  {label}>  ({len(html)} chars)")
            # リンク自身は既に分かっているので、祖先だけ中身を出す
            if depth > 0:
                print(f"      {html[:_SNIPPET]}")
            node, depth = node.parent, depth + 1


def main() -> None:
    wanted = [s.strip() for s in (sys.argv[1] if len(sys.argv) > 1 else "").split(",")]
    wanted = [s for s in wanted if s]
    # 第2引数は試したいセレクタ候補 ("|" 区切り)。セレクタ自体にカンマを
    # 使えるようにしたいので区切りはカンマではない
    raw = sys.argv[2] if len(sys.argv) > 2 else ""
    selectors = [s.strip() for s in raw.split("|") if s.strip()]
    # 第3引数は一覧ページの URL 差し替え
    url_override = sys.argv[3].strip() if len(sys.argv) > 3 else ""
    config = load_config(Path("./config/config.yaml"))

    if not wanted:
        print("ソース名を指定してください。利用可能:", ", ".join(config))
        return

    for name in wanted:
        if name not in config:
            print(f"\n[SKIP] {name}: config に存在しません")
            continue
        site = config[name]
        # 一覧ページを差し替えて試せるようにする。トップより記事一覧
        # ページのほうが件数が多いことがある
        if url_override:
            site = replace(site, news_home=url_override)
        try:
            inspect(name, site, selectors)
        except Exception as e:
            print(f"[FAIL] {name}: {e}")


if __name__ == "__main__":
    main()
