# F1 News

F1関連ニュースを複数サイトからスクレイピングし、静的サイトとして S3 でホスティングするツール。

## 仕組み

```
GitHub Actions (15分ごと / mainへのpush時)
  → scrape_news() で各サイトをスクレイピング
  → analyze_trends() で収集タイトルを簡易NLP解析（トレンド算出）
  → generate.py が Jinja2 テンプレートで index.html を生成
  → AWS S3 にアップロード → 静的サイトとして公開
```

## タブ

| タブ | 内容 |
|---|---|
| NEWS | 各ソースの最新ニュース一覧 |
| TRENDS | 直近ニュースの話題トレンド（ホットなドライバー / チーム / トピック / キーワード） |
| SCHEDULE | シーズンスケジュール（Jolpica API） |

## トレンド解析 (`modules/trends.py`)

収集済みの記事タイトル（日英混在）だけを対象に、**LLM や外部APIを一切使わず**
トレンドを算出する。追加の依存ライブラリも不要で、GitHub Actions 上で無料・確実に動く。

- **ホットなドライバー / チーム**: 日英の別名辞書 (gazetteer) で言及記事数をカウント
- **トピック**: 「予選・契約・クラッシュ」等のキーワード辞書でカテゴリ集計
- **トレンドキーワード**: 辞書に無い語（サーキット名・突発イベント等）を
  カタカナ / 漢字 / 英単語の出現頻度から抽出

数字はいずれも「その語に言及した記事数」。辞書ベースの簡易解析のため目安として扱う。
ドライバー / チームの追加・変更は `modules/trends.py` の `_DRIVERS` / `_TEAMS` /
`_TOPICS` を編集するだけでよい。

## ソース一覧

| サイト | 方式 |
|---|---|
| motorsport.com (JP) | RSS |
| F1速報 (F速) | HTML scraping |
| TopNews | RSS |
| Formula1-Data | RSS |
| web Sportiva (集英社) | HTML scraping |
| F1SNS日本語訳 | RSS |
| Shiga Sports F1 | HTML scraping |
| BBC Sport F1 | RSS |
| Sky Sports F1 | HTML scraping |
| motorsport.com (EN) | RSS |
| F1-Gate | HTML scraping |
| F1情報通 | RSS |

## 構成

```
config/config.yaml        # スクレイピング設定
modules/
  load_config.py          # 設定読み込み
  scraper.py              # HTML / RSS スクレイパー
  schedule.py             # シーズンスケジュール取得 (Jolpica API)
  trends.py               # 簡易NLPによるトレンド解析（辞書ベース・LLM不使用）
  structure.py            # データクラス定義
templates/index.html.j2   # Jinja2 + Alpine.js テンプレート
generate.py               # HTML 生成スクリプト
template.yaml             # CloudFormation (S3バケット定義)
.github/workflows/deploy.yml  # GitHub Actions ワークフロー
```

## 更新間隔について

GitHub はスケジュールイベントをかなりの割合で捨てる。2026-09-15 の実測（15日間・
200実行）では、4回/時を要求して**実際に発火したのは 13.7%** だった。発火したものは
待ち時間 0 分で即実行できているので、ランナー不足ではなくイベント自体が届いていない。
発火率は UTC 02-03時 の 4.9% から UTC 23時 の 27.9% まで時間帯で変動する。

これはこちらから制御できないため、2段構えで対処している。

1. **cron を 5分ごと**（GitHub が許す最短）にして試行回数を増やす
2. **1回の実行を `LOOP_MINUTES` のあいだ持続**させ、`INTERVAL_MINUTES` ごとに
   生成とアップロードを繰り返す

これにより、スケジュールが平均1.8時間に1回しか届かなくても、実際の更新間隔は
`INTERVAL_MINUTES`（既定15分）で決まる。新しい実行が始まれば `concurrency` により
古いループは打ち切られるので、二重に更新されることはない。

間隔を変えたい場合は `.github/workflows/deploy.yml` の `INTERVAL_MINUTES` と
`LOOP_MINUTES` を調整する（`LOOP_MINUTES` はジョブの `timeout-minutes` 未満にする）。

## AWS インフラ

CloudFormation (`template.yaml`) で S3 バケットを管理。
初回は GitHub Actions が自動でスタックを作成する。

必要な GitHub Secrets:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
