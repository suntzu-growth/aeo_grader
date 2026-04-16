from __future__ import annotations

from datetime import datetime
from google.cloud import storage

BUCKET_NAME = "aeo-grader-informes"
PREFIX = "informes/"


def upload_html_to_gcs(html: str, filename: str) -> str:
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)

    blob = bucket.blob(f"{PREFIX}{filename}")
    blob.upload_from_string(html, content_type="text/html")

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{blob.name}?authuser=1"


def list_informes_from_gcs() -> dict:
    client = storage.Client()
    blobs = client.list_blobs(BUCKET_NAME, prefix=PREFIX)

    items = []
    for blob in blobs:
        if blob.name.endswith(".html"):
            items.append(
                {
                    "name": blob.name.split("/")[-1],
                    "path": blob.name,
                    "url": f"https://storage.googleapis.com/{BUCKET_NAME}/{blob.name}?authuser=1",
                    "size": blob.size,
                    "created": blob.time_created.isoformat() if blob.time_created else None,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                }
            )

    items.sort(key=lambda x: x["created"] or "", reverse=True)

    return {
        "count": len(items),
        "items": items,
    }