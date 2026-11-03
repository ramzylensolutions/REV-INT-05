import boto3
import os
from dotenv import load_dotenv
load_dotenv()
sqs = boto3.client(
    "sqs",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)
queue_url= sqs.get_queue_url(
    QueueName=os.getenv("SCORING_QUEUE_NAME"))["QueueUrl"]
sqs.purge_queue(QueueUrl=queue_url)
print("Queue Purged")