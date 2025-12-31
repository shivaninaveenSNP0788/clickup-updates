import requests
import json
from datetime import datetime, timedelta, date

API_TOKEN = "pk_218696006_UXYXEI6AKDLMXJ3P4INX79SD9ZO0UTF0"
LIST_ID = "901412176234"
TAG_FILTER = "%23new"

FIELD_COMMERCE_PLATFORM = "4927273a-9c1f-4042-8aca-5fd4d14fa26a"

FIELD_MAP = {
    "Kickoff": "7c302bd2-027a-4f17-b795-c3f55a044868",
    "Design": "8425e4a9-2dc3-4064-88ce-629706717aab",
    "Integration": "ed0a3f9a-824d-40cd-9b43-4fb72e1876f4",
    "PreGoLive": "afc4d2a9-4a58-4038-b96d-248a7c7d765e",
    "QA": "59bfc489-64c2-402a-bf35-865116d22af5",
    "GoLive": "7344338c-1889-443b-b698-9924c9c936f2"
}

STAGE_ORDER = ["Kickoff", "Design", "Integration", "PreGoLive", "QA", "GoLive"]

STAGE_OFFSETS = {
    "shopify": {"Kickoff": 2, "Design": 2, "Integration": 2, "PreGoLive": 1, "QA": 1, "GoLive": 1},
    "rich": {"Kickoff": 2, "Design": 5, "Integration": 7, "PreGoLive": 2, "QA": 4, "GoLive": 1},
    "custom": {"Kickoff": 2, "Design": 6, "Integration": 20, "PreGoLive": 2, "QA": 4, "GoLive": 1}
}

headers = {"Authorization": API_TOKEN}

with open("config/holidays.json") as f:
    HOLIDAYS = {datetime.strptime(d, "%Y-%m-%d").date() for d in json.load(f)["holidays"]}

def add_workdays(start_date, days):
    current = start_date
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5 and current.date() not in HOLIDAYS:
            days -= 1
    return current

def run():
    tasks = requests.get(
        f"https://api.clickup.com/api/v2/list/{LIST_ID}/task?tags[]={TAG_FILTER}",
        headers=headers
    ).json()["tasks"]

    for task in tasks:
        task_id = task["id"]
        created = datetime.fromtimestamp(int(task["date_created"]) / 1000)

        platform = "custom"
        for f in task["custom_fields"]:
            if f["id"] == FIELD_COMMERCE_PLATFORM and f.get("value"):
                name = f["value"].lower()
                if "shopify" in name:
                    platform = "shopify"
                elif any(p in name for p in ["woo", "magento", "sfcc", "big"]):
                    platform = "rich"

        current_date = created

        for stage in STAGE_ORDER:
            offset = STAGE_OFFSETS[platform][stage]
            current_date = add_workdays(current_date, offset)

            payload = {
                "value": int(current_date.timestamp() * 1000),
                "value_options": {"time": True}
            }

            requests.post(
                f"https://api.clickup.com/api/v2/task/{task_id}/field/{FIELD_MAP[stage]}",
                headers=headers,
                json=payload
            )

        print(f"✅ {task_id} updated | {platform}")

if __name__ == "__main__":
    run()
