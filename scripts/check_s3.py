import os
import json
import boto3
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

bucket = os.getenv("AUDIT_BUCKET_NAME")

# List all files
response = s3.list_objects_v2(Bucket=bucket)
files = response.get("Contents", [])
print(f"Total files: {len(files)}")

for item in files[:5]:
    print(item["Key"])

# Open the first file and print its content
if files:
    obj = s3.get_object(Bucket=bucket, Key=files[0]["Key"])
    print(json.dumps(json.loads(obj["Body"].read()), indent=2))