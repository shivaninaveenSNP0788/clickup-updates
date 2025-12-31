import json
import requests
from datetime import datetime, timedelta, date
from urllib.parse import unquote

# ---------------- CONFIG LOADERS ---------------- #

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

# ---------------- WORKING DAYS CALCULATOR ---------------- #

class WorkingDaysCalculator:
    def __init__(self, holidays_file):
        self.holidays = self._load_holidays(holidays_file)

    def _load_holidays(self, path):
        try:
            data = load_json(path)
            return {
                datetime.strptime(d, "%Y-%m-%d").date()
                for d in data.get("holidays", [])
            }
        except Exception:
            return set()

    def is_working_day(self, d):
        return d.weekday() < 5 and d not in self.holidays

    def calculate(self, start_date, end_date):
        if start_date > end_date:
            return 0

        count = 0
        current = start_date
        while current < end_date:
            if self.is_working_day(current):
                count += 1
            current += timedelta(days=1)
        return count

# ---------------- CLICKUP CLIENT ---------------- #

class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self, config):
        self.headers = {
            "Authorization": config["api_token"],
            "Content-Type": "application/json"
        }
        self.list_id = config["list_id"]
        self.kickoff_field_id = config["kickoff_field_id"]
        self.go_live_field_id = config["go_live_field_id"]
        self.aging_field_id = config["aging_field_id"]
        #self.required_tag = config["required_tag"].lower()
        self.required_tag = unquote(config["required_tag"]).lower()
        print("🔎 Matching tag:", self.required_tag)

        self.calculator = WorkingDaysCalculator("config/holidays.json")

    def get_tasks(self):
        url = f"{self.BASE_URL}/list/{self.list_id}/task"
        params = {"include_closed": "true", "subtasks": "false"}

        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json().get("tasks", [])
        print("tasks", response.json().get("tasks", [])) break

    def update_field(self, task_id, value):
        url = f"{self.BASE_URL}/task/{task_id}/field/{self.aging_field_id}"
        return requests.post(
            url,
            headers=self.headers,
            json={"value": str(value)}
        ).ok

    @staticmethod
    def get_custom_field(task, field_id):
        for field in task.get("custom_fields", []):
            if field["id"] == field_id and field.get("value"):
                if field["type"] == "date":
                    return datetime.fromtimestamp(int(field["value"]) / 1000).date()
                return field["value"]
        return None

    @staticmethod
    def has_required_tag(task, tag):
        return tag in [t["name"].lower() for t in task.get("tags", [])]

# ---------------- MAIN LOGIC ---------------- #

LIVE_STATUSES = {"live", "prod qa", "hypercare"}

def main():
    try:
        config = load_json("config/clickup_config.json")
    except Exception as e:
        print(f"❌ Failed to load ClickUp config: {e}")
        return

    client = ClickUpClient(config)
    tasks = client.get_tasks()

    updated = skipped = 0
    today = date.today()

    for task in tasks:
        name = task["name"]
        status = task["status"]["status"].lower()

        if not client.has_required_tag(task, client.required_tag):
            continue

        kickoff = client.get_custom_field(task, client.kickoff_field_id)
        if not kickoff:
            print(f"⊘ Skipped: {name} (No kickoff date)")
            skipped += 1
            continue

        go_live = client.get_custom_field(task, client.go_live_field_id)

        if status in LIVE_STATUSES:
            if not go_live:
                print(f"⊘ Skipped: {name} (Missing Go Live Date)")
                skipped += 1
                continue
            end_date = go_live
        else:
            end_date = today

        aging = client.calculator.calculate(kickoff, end_date)

        if client.update_field(task["id"], aging):
            print(f"✓ {name} [{task['status']['status']}] → Aging: {aging}")
            updated += 1
        else:
            print(f"✗ Failed update: {name}")
            skipped += 1

    print("\n" + "=" * 60)
    print(f"Summary: {updated} updated | {skipped} skipped")
    print("=" * 60)

# ---------------- ENTRY POINT ---------------- #

if __name__ == "__main__":
    main()
