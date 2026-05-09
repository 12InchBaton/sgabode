"""Cloudflare R2 storage service (S3-compatible)."""

import uuid
import mimetypes
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from config import settings


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


async def upload_file(
    file_data: bytes,
    original_filename: str,
    folder: str = "listings",
) -> str:
    """Upload bytes to R2 and return the public URL."""
    ext = Path(original_filename).suffix.lower() or ".bin"
    key = f"{folder}/{uuid.uuid4().hex}{ext}"
    content_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"

    client = _r2_client()
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_data,
        ContentType=content_type,
    )
    return f"{settings.R2_PUBLIC_URL}/{key}"


async def delete_file(url: str) -> bool:
    """Delete a file from R2 by its public URL."""
    prefix = f"{settings.R2_PUBLIC_URL}/"
    if not url.startswith(prefix):
        return False
    key = url[len(prefix):]
    try:
        client = _r2_client()
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
        return True
    except ClientError:
        return False


async def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a time-limited presigned URL for a private object."""
    client = _r2_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )
