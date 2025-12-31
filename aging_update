import requests
import json
import os
from datetime import datetime, timedelta

# ============================
# CONFIGURATION
# ============================

API_TOKEN = "pk_218696006_UXYXEI6AKDLMXJ3P4INX79SD9ZO0UTF0"
LIST_ID = "901412176234"
TAG_FILTER = "%23new"

headers = {"Authorization": API_TOKEN}

# ============================
# FIELD IDS (UPDATE THESE)
# ============================

FIELD_ACTUAL_KICKOFF = "8ebce881-1682-4de9-b2a2-f449a90ccdd3"
FIELD_AGING = "04713aad-23e4-4e5b-ae40-05a0c944025a"

# ============================
# LOAD HOLIDAYS
# ============================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOLIDAY_FILE = os.path.join(BASE_DIR, "config", "holidays.json")

with open(HOLIDAY_FILE, "r") as f:
    HOLIDAYS = {
        datetime.strptime(d, "%Y-%m-%d").date()
        for d in json.load(f)["holidays"]
    }

print(f"✅ Loaded {len(HOLIDAYS)} holidays")

# ============================
# DATE HELPERS
# ============================

def working_days_between(start_date, end_date):
    """
    Calculates working days between two dates
    excluding weekends and public holidays.
    """
    if not start_date or end_date < start_date:
        return 0

    days = 0
    current = start_date

    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5 and current.date() not in HOLIDAYS:
            days += 1

    return days

# ============================
# CLICKUP HELPERS
# ============================

def get_all_tasks():
    tasks, page = [], 0
    while True:
        url = f"https://api.clickup.com/api/v2/list/{LIST_ID}/task?page={page}&tags[]={TAG_FILTER}"
        r = requests.get(url, headers=headers)
        data = r.json()

        if not data.get("tasks"):
            break

        tasks.extend(data["tasks"])
        page += 1

    return tasks

def get_actual_kickoff(task):
    for f in task.get("custom_fields", []):
        if f["id"] == FIELD_ACTUAL_KICKOFF and f.get("value"):
            return datetime.fromtimestamp(int(f["value"]) / 1000)
    return None

def update_aging(task_id, aging_days):
    url = f"https://api.clickup.com/api/v2/task/{task_id}/field/{FIELD_AGING}"
    payload = {"value": aging_days}
    requests.post(url, headers=headers, json=payload)

# ============================
# MAIN
# ============================

def run():
    tasks = get_all_tasks()
    today = datetime.today()

    updated = skipped = 0

    print(f"🔎 Processing {len(tasks)} tasks")

    for task in tasks:
        task_id = task["id"]
        kickoff_date = get_actual_kickoff(task)

        if not kickoff_date:
            skipped += 1
            continue

        aging = working_days_between(kickoff_date, today)
        update_aging(task_id, aging)

        updated += 1
        print(f"✅ {task_id} | Aging: {aging} working days")

    print("\n==============================")
    print(f"UPDATED : {updated}")
    print(f"SKIPPED : {skipped} (No Actual Kickoff)")
    print("==============================")

if __name__ == "__main__":
    run()
