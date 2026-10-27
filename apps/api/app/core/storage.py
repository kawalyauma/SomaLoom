"""Object-key abstraction. EBS encryption is a host prerequisite, not an app flag."""

import os
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID, uuid4


class ObjectStore(Protocol):
    def put(self, tenant_id: UUID, key: str, content: bytes) -> str: ...
    def get(self, tenant_id: UUID, key: str) -> bytes: ...


class LocalObjectStore:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, tenant_id: UUID, key: str) -> Path:
        tenant_id = UUID(str(tenant_id))
        parts = PurePosixPath(key)
        if not key or parts.is_absolute() or ".." in parts.parts or "\\" in key:
            raise ValueError("Invalid object key")
        root = self.root / str(tenant_id)
        path = root.joinpath(*parts.parts)
        if not path.resolve().is_relative_to(root.resolve()) or root.is_symlink():
            raise ValueError("Object key escaped tenant root")
        return path

    def put(self, tenant_id: UUID, key: str, content: bytes) -> str:
        path = self.path(tenant_id, key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = path.with_name(f".{uuid4()}.tmp")
        try:
            with temp.open("xb") as stream:
                os.chmod(temp, 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic publication without overwriting an immutable resource version.
            os.link(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return key

    def get(self, tenant_id: UUID, key: str) -> bytes:
        if key.startswith("telegram-account/"):
            from services.ingestion.telegram_links import archive_content
            return archive_content(tenant_id, key)
        return self.path(tenant_id, key).read_bytes()


class S3ObjectStore:
    def __init__(self, bucket: str, kms_key_id: str):
        import boto3

        self.client = boto3.client("s3")
        self.bucket, self.kms_key_id = bucket, kms_key_id

    def key(self, tenant_id: UUID, key: str):
        if (
            not key
            or PurePosixPath(key).is_absolute()
            or ".." in PurePosixPath(key).parts
            or "\\" in key
        ):
            raise ValueError("Invalid object key")
        return f"{UUID(str(tenant_id))}/{key}"

    def put(self, tenant_id: UUID, key: str, content: bytes) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(tenant_id, key),
            Body=content,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
            IfNoneMatch="*",
        )
        return key

    def get(self, tenant_id: UUID, key: str) -> bytes:
        if key.startswith("telegram-account/"):
            from services.ingestion.telegram_links import archive_content
            return archive_content(tenant_id, key)
        return self.client.get_object(Bucket=self.bucket, Key=self.key(tenant_id, key))[
            "Body"
        ].read()


def configured_store():
    """All pipeline stages use the same durable storage configuration."""
    from app.core.config import get_settings

    bucket = os.getenv("SOMALOOM_STORAGE_BUCKET") or os.getenv("INGESTION_S3_BUCKET")
    kms = os.getenv("SOMALOOM_KMS_KEY_ID") or os.getenv("INGESTION_S3_KMS_KEY")
    if bool(bucket) != bool(kms):
        raise RuntimeError("Both storage bucket and KMS key are required")
    if bucket:
        return S3ObjectStore(bucket, kms)
    return LocalObjectStore(get_settings().storage_root)
