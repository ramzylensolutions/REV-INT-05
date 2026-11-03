import asyncpg
import os
from contextlib import asynccontextmanager
import boto3
from dotenv import load_dotenv
import asyncio
from app.config import Settings
import json,signal
from scripts.handlers import MalformedJob,require,score_account
from scripts.idempotency import already_done, mark_done
load_dotenv()
stop = False
def handle_stop(signum, frame):
    global stop
    print("Stop signal received: finishing the current message, then exiting")
    stop = True
@asynccontextmanager
async def create_pool():
    pool = await asyncpg.create_pool(
        user=Settings.db_user,
        password=Settings.db_pass,
        database=Settings.db_name,
        host=Settings.db_host,
        port=Settings.db_port
    )
    yield pool
    await pool.close()
HANDLERS={"score_account":score_account}
def parse_job(body: str) -> dict:
    try:
        job = json.loads(body)
    except json.JSONDecodeError as error:
        raise MalformedJob(f"bad JSON: {error}")

    if not isinstance(job, dict):
        raise MalformedJob("body is not a JSON object")

    require(job, "account_id","task", "idempotency_key")

    if job["task"] not in HANDLERS:
        raise MalformedJob(f"unknown job_type: {job['task']}")

    return job

async def main():
    signal.signal(signal.SIGTERM, handle_stop)  
    signal.signal(signal.SIGINT, handle_stop)

    sqs = boto3.client(
    "sqs",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    queue_url = sqs.get_queue_url(QueueName=os.getenv("SCORING_QUEUE_NAME"))["QueueUrl"]
    dlq_url =  sqs.get_queue_url(QueueName=os.getenv("SCORING_DLQ_NAME"))["QueueUrl"]
    async with create_pool() as pool:
        while not stop:
            response = await asyncio.to_thread(
                sqs.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,
            )
            messages = response.get("Messages",[])
            if not messages:
                print("No messages, pulling again")
                continue
            for message in messages:
                message_id = message["MessageId"]
                print("Got message:", message_id, message["Body"])
                try:
                    job = parse_job(message["Body"])
                    key = job["idempotency_key"]

                    previous = await asyncio.to_thread(already_done,s3,Settings.AUDIT_BUCKET_NAME, key)
                    if previous is not None:
                        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                        print("Duplicate, skipped:", message_id, "key", key)
                        continue

                    handler = HANDLERS[job["task"]]    
                    result = await handler(job["account_id"],pool)

                    await asyncio.to_thread(mark_done,s3,Settings.AUDIT_BUCKET_NAME, key, {
                        "job_type": job["task"],
                        "message_id": message_id,
                        "result": result,
                    })
                except MalformedJob as error:
                    sqs.send_message(
                        QueueUrl=dlq_url,
                        MessageBody=message["Body"],
                        MessageAttributes={
                            "error": {"DataType": "String", "StringValue": str(error)},
                            "original_message_id": {"DataType": "String", "StringValue": message_id},
                        },
                    )
                    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                    print("Parked malformed message:", message_id, error)
                    continue
                except Exception as error:
                    print("Handler failed, not deleting:", message_id, error)
                    continue
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                print("Done:", message_id, result)
    print("Worker stopped cleanly")

if __name__ == "__main__":
    asyncio.run(main())