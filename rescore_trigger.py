import httpx
import argparse
import json
from dotenv import load_dotenv
import os
load_dotenv()
parser = argparse.ArgumentParser()
parser = argparse.ArgumentParser()
parser.add_argument("account_id")
parser.add_argument("--employees", type=int)
parser.add_argument("--country")
args = parser.parse_args()
body = {}
if args.employees is not None:
    body["employees"] = args.employees
if args.country is not None:
    body["country"] = args.country
url = f"{os.getenv('API_BASE_URL')}/accounts/{args.account_id}/rescore"
headers = {"Authorization": f"Bearer {os.getenv('API_TOKEN')}"}
response = httpx.post(url, headers=headers, json=body)

# 4. print result
if response.status_code == 202:
    print("Rescore queued")
elif response.status_code == 404:
    print("Account not found")
else:
    print(f"Failed ({response.status_code}): {response.text}")