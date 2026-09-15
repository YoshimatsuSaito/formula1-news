# F1 News

F1関連ニュースを複数サイトからスクレイピングし、静的サイトとして S3 でホスティングするツール。

## 仕組み

```
EventBridge (15分ごと) → Lambda   ※mainへのpush時はGitHub Actionsからも実行
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
トレンドを算出する。追加の依存ライブラリも不要で、Lambda の無料枠内で動く。

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
generate.py               # HTML 生成（build_html で文字列を返す）
lambda_handler.py         # Lambda エントリポイント（生成してS3へput）
tools/inspect_source.py   # 対象サイトの実HTMLを確認する診断ツール
template.yaml             # CloudFormation (S3 / Lambda / EventBridge)
.github/workflows/deploy.yml   # スタック更新と Lambda コード配布
.github/workflows/inspect.yml  # 診断ツールの手動実行
```

## 定期実行を GitHub Actions から AWS へ移した経緯

**GitHub Actions の `schedule` は使い物にならなかった。** 2026-09-15 の実測では、
4回/時を要求して実際に発火したのは **13.7%**。発火したものは待ち時間 0 分で
即実行できており、ランナー不足ではなくイベント自体が届いていない。

cron を 5分ごと（12回/時）に増やして検証したが、**直後の 3時間15分で配信は 0 件**
だった（本来なら39回）。要求回数を増やしても配信数は変わらず、リポジトリ単位の
配信上限があると見られる。cron の調整では解決しない。

そこで定期実行を **EventBridge + Lambda** に移した。

- `ScraperSchedule`（EventBridge Rule）が `UpdateIntervalMinutes`（既定15分）ごとに
  `ScraperFunction`（Lambda）を起動する
- Lambda は `lambda_handler.handler` から `generate.build_html()` を呼び、
  結果を S3 に直接 put する
- 間隔を変えるときは `template.yaml` の `UpdateIntervalMinutes` を変える

GitHub Actions に残っているのは「コードを配る」役割だけで、`schedule` トリガは
削除した。main への push 時に CloudFormation スタックを更新し、Lambda のコードを
差し替え、最後に invoke して動作確認とページの更新をまとめて行う。

### Lambda のパッケージング

`lxml` がネイティブ拡張なので、ランナー任せに `pip install` すると
アーキテクチャ違いでインポートに失敗する。CI では実行環境を明示して取得している。

```
pip install -r requirements.txt --target build \
  --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.11 --only-binary=:all:
```

`boto3` は Lambda ランタイムに同梱されているのでパッケージに含めない。
zip は約 7MB で、直接アップロードの上限 50MB に収まる。

## AWS インフラ

CloudFormation (`template.yaml`) で S3 バケット、スクレイパーの Lambda、
その定期実行ルールを管理する。初回は GitHub Actions が自動でスタックを作成する。

必要な GitHub Secrets:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
