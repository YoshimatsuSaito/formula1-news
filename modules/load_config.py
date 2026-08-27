from pathlib import Path

import yaml

from .structure import SiteStructure


def load_config(config_path: Path) -> dict[str, SiteStructure]:
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    dict_site_structure = {}
    for site, info in config["sites"].items():
        source = info.get("source", "html")
        if source == "rss":
            dict_site_structure[site] = SiteStructure(
                source="rss",
                news_home=info["news_home"],
                rss_url=info["rss_url"],
            )
        else:
            dict_site_structure[site] = SiteStructure(
                source="html",
                prefix_home=info.get("prefix_home", ""),
                news_home=info["news_home"],
                scrape_title=info["scrape_title"],
                scrape_link=info["scrape_link"],
                get_title=eval(info["get_title"]),
                get_link=eval(info["get_link"]),
            )
    return dict_site_structure
