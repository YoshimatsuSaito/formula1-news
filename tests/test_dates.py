"""実サイトと同じ構造を組んで、掲載日の読み取りを確かめる。

ネットワークを使わずに回帰を見られるようにしてある。
"""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup as bs

from modules.scraper import _JST, _heading_date, _html_text_date, _parse_text_date

TODAY = datetime.now(_JST).date()
Y = TODAY.year
ok = fail = 0


def check(label, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  OK   {label}: {got!r}")
    else:
        fail += 1
        print(f"  NG   {label}: {got!r} (期待 {want!r})")


# ---------------------------------------------------------------- F1速報
# 日付は <ul> の中の <h2> 見出しで区切られ、記事自身は日付を持たない。
# <ul> には20件ぶんのリンクが入っている。
LINK = 'a[href*="news/sp/body"]'
items = []
for day, titles in ((6, ["ルクレール、4位"]), (5, ["アウディF1リバリー", "2027年1月1日から施行される新規定"])):
    items.append(f"<h2>10/{day}更新</h2>")
    for i, t in enumerate(titles):
        items.append(
            f'<li><a href="index.php?page=news/sp/body&no={day}{i}">'
            f'<span class="cont_photo"><img/></span>'
            f'<span class="cont_text">{t}</span></a></li>'
        )
sokuho = bs(
    f'<div class="text_area"><h2 id="list_title">最新ニュース一覧</h2>'
    f'<ul>{"".join(items)}</ul></div>',
    "lxml",
)
links = sokuho.select(LINK)
print("\nF1速報 (日付は見出し、記事自身は日付なし、一覧に複数記事):")
# 1件目: 10/6更新 の下
el, title = links[0], "ルクレール、4位"
check("周辺テキスト（他記事を跨がない）", _html_text_date(el, title, LINK), "")
check("見出しから", _heading_date(el), date(Y, 10, 6).isoformat())
# 2件目: 10/5更新 の下
el, title = links[1], "アウディF1リバリー"
check("周辺テキスト（他記事を跨がない）", _html_text_date(el, title, LINK), "")
check("見出しから", _heading_date(el), date(Y, 10, 5).isoformat())
# タイトルに 2027年1月1日 を含む記事でも、見出しの日付が使われる
el, title = links[2], "2027年1月1日から施行される新規定"
check("タイトルの未来日付を拾わない", _html_text_date(el, title, LINK), "")
check("見出しから", _heading_date(el), date(Y, 10, 5).isoformat())

# ---------------------------------------------------------------- F1-Gate
# カードの <a> の中にタイトルと掲載日が並ぶ。<time> は無い。
# div.fv-top には2件のカードが入っている。
LINK2 = "article.fv-lead > a"
gate = bs(
    '<div class="fv-top">'
    '<article class="fv-lead"><a href="/honda/1.html"><div class="ph"><img/></div>'
    '<div class="hero-body"><span class="cat">ホンダF1</span>'
    "<h2>新ターボ投入の効果を評価</h2>"
    f"<p>{Y}年10月6日 08:01</p></div></a></article>"
    '<article class="fv-lead"><a href="/mercedes/2.html"><div class="ph"><img/></div>'
    '<div class="hero-body"><span class="cat">メルセデスF1</span>'
    "<h2>ラッセルのPU故障に激怒</h2>"
    f"<p>{Y}年10月5日 07:03</p></div></a></article>"
    "</div>",
    "lxml",
)
cards = gate.select(LINK2)
print("\nF1-Gate (カード内に掲載日、<time> なし、隣にも記事):")
check("自分の日付を読む", _html_text_date(cards[0], "新ターボ投入の効果を評価", LINK2),
      date(Y, 10, 6).isoformat())
check("隣の日付を読まない", _html_text_date(cards[1], "ラッセルのPU故障に激怒", LINK2),
      date(Y, 10, 5).isoformat())

# ---------------------------------------------------------------- 未来日付
print("\n未来の掲載日は採らない:")
future = (TODAY + timedelta(days=40))
check(f"{future} は捨てる",
      _parse_text_date(f"{future.year}年{future.month}月{future.day}日"), None)
yesterday = TODAY - timedelta(days=1)
check(f"{yesterday} は残す",
      _parse_text_date(f"{yesterday.year}年{yesterday.month}月{yesterday.day}日"),
      yesterday)

# ---------------------------------------------------------------- タイトル内の日付
print("\nタイトルに含まれる日付を掲載日と取り違えない:")
LINK3 = "li > a"
sched = bs(
    '<ul><li><a href="/x.html">8月29日開催のテスト</a></li></ul>', "lxml"
)
el = sched.select(LINK3)[0]
check("タイトルだけの記事", _html_text_date(el, "8月29日開催のテスト", LINK3), "")

print(f"\n{ok} OK / {fail} NG")
sys.exit(1 if fail else 0)
