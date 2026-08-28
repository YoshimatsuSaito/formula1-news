import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from jinja2 import Environment, FileSystemLoader, select_autoescape

from modules.load_config import load_config
from modules.schedule import fetch_season_schedule
from modules.scraper import scrape_news
from modules.structure import SiteStructure
from modules.trends import analyze_trends

JST = timezone(timedelta(hours=9))


def main() -> None:
    config = load_config(Path("./config/config.yaml"))

    sources = [_collect(name, site) for name, site in config.items()]
    fetched = sum(1 for s in sources if s["articles"])

    year = datetime.now(JST).year
    schedule = []
    try:
        schedule = fetch_season_schedule(year)
        print(f"[OK] schedule: {len(schedule)} rounds (year={year})")
    except Exception as e:
        print(f"[WARN] schedule: {e}")

    trends = {}
    try:
        trends = analyze_trends(sources)
        print(
            f"[OK] trends: {trends['total_articles']} titles analyzed "
            f"({len(trends['drivers'])} drivers, {len(trends['teams'])} teams, "
            f"{len(trends['topics'])} topics, {len(trends['keywords'])} keywords)"
        )
    except Exception as e:
        print(f"[WARN] trends: {e}")

    updated_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    html = _render(sources, schedule, trends, year, updated_at)
    Path("index.html").write_text(html, encoding="utf-8")
    print(
        f"\nGenerated index.html "
        f"({fetched}/{len(sources)} sources with articles, {updated_at})"
    )


def _collect(name: str, site: SiteStructure) -> dict:
    """1ソース分の記事を取得する。

    取得に失敗しても枠は残す。ソース名のリンクからサイト自体には飛べるので、
    項目ごと消えるより「今は取れていない」と分かるほうがよい。
    """
    articles: list[dict] = []
    note = ""

    try:
        result = scrape_news(name=name, site_structure=site)
        articles = [
            {"title": t, "link": l}
            for t, l in zip(result.list_title, result.list_link)
            if t and l
        ]
        if articles:
            print(f"[OK] {name}: {len(articles)} items")
        else:
            note = "記事を取得できませんでした"
            print(f"[SKIP] {name}: 0 items")
    except Exception as e:
        note = "取得に失敗しました"
        print(f"[FAIL] {name}: {e}")

    return {
        "key":      name.lower().replace(" ", "-").replace("/", "-"),
        "name":     name,
        "url":      site.news_home,
        "articles": articles,
        "note":     note,
    }


def _render(
    sources: list[dict],
    schedule: list[dict],
    trends: dict,
    year: int,
    updated_at: str,
) -> str:
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("index.html.j2")
    return template.render(
        sources=sources,
        source_keys_json=json.dumps([s["key"] for s in sources]),
        schedule=schedule,
        trends=trends,
        current_year=year,
        updated_at=updated_at,
    )


if __name__ == "__main__":
    main()
