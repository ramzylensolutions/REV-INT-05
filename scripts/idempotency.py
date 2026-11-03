import json

from botocore.exceptions import ClientError
def _key_path(idempotency_key: str) -> str:
    return f"idempotency/{idempotency_key}.json"


def already_done(s3, bucket: str, idempotency_key: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=bucket, Key=_key_path(idempotency_key))
    except ClientError as error:
        if error.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read())

def mark_done(s3, bucket: str, idempotency_key: str, record: dict) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=_key_path(idempotency_key),
        Body=json.dumps(record),
        ContentType="application/json",
    )