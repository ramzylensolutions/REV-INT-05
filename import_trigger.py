import httpx
import argparse
import json
from dotenv import load_dotenv
import os
load_dotenv()
parser = argparse.ArgumentParser()
parser.add_argument("file")
args = parser.parse_args()
with open (f"Data/{args.file}",encoding="utf-8") as f:
    companies = json.load(f)
api_base_url = os.getenv("api_base_url")
api_token = os.getenv("api_token")
headers = {"Authorization":f"Bearer {api_token}"}
for i,company in enumerate(companies,start=1):
    try:
        response = httpx.post(f"{api_base_url}/companies", headers=headers, json=company)
        if response.status_code in (200, 201):
            print(f"Line {i}: imported")
        elif response.status_code == 409:
            print(f"Line {i}: already exists, skipped")
        else:
            print(f"Line {i}: failed ({response.status_code}) {response.text}")
    except Exception as e:
        print(f"Line {i}: error ({e})")
print(response.text)
    