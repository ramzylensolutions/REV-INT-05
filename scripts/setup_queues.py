import os
import boto3
from dotenv import load_dotenv
import json
load_dotenv()
sqs = boto3.client(
    "sqs",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)
dlq = sqs.create_queue(QueueName=os.getenv("SCORING_DLQ_NAME"))
dlq_url = dlq["QueueUrl"]

dlq_attributes = sqs.get_queue_attributes(
    QueueUrl=dlq_url,
    AttributeNames=["QueueArn"],
)
dlq_arn = dlq_attributes["Attributes"]["QueueArn"]


redrive_policy = {
    "deadLetterTargetArn": dlq_arn,
    "maxReceiveCount": "3",
}

jobs = sqs.create_queue(
    QueueName=os.getenv("SCORING_QUEUE_NAME"),
    Attributes={
        "RedrivePolicy": json.dumps(redrive_policy),
        "VisibilityTimeout": "30",
    },
)
jobs_url = jobs["QueueUrl"]
print(sqs.get_queue_attributes(
    QueueUrl=jobs_url,
    AttributeNames=["ApproximateNumberOfMessages"],
)["Attributes"])

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),)
s3.create_bucket(Bucket=os.getenv("AUDIT_BUCKET_NAME"))