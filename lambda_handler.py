"""EventBridge から定期実行され、ページを生成して S3 に置く Lambda ハンドラ。

GitHub Actions の schedule はイベント自体が配信されないことが多く
（2026-09-15 の実測で配信率 13.7%、3時間以上の無配信も観測）、
更新間隔が安定しなかったため、定期実行を EventBridge に移した。
"""
import os

import boto3

import generate

_s3 = boto3.client("s3")


def handler(event, context):
    bucket = os.environ["BUCKET_NAME"]
    key = os.environ.get("OBJECT_KEY", "index.html")

    html = generate.build_html()

    _s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        # 常に最新を配信する。生成のたびに内容が変わるのでキャッシュさせない
        CacheControl="no-cache, max-age=0",
    )

    print(f"Uploaded s3://{bucket}/{key} ({len(html)} chars)")
    return {"bucket": bucket, "key": key, "bytes": len(html.encode("utf-8"))}
