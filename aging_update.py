import json
import requests
from datetime import datetime, timedelta
import sys
import urllib.parse


# ======================================================
# Working Days Calculator
# ======================================================
class WorkingDaysCalculator:
    def __init__(self, holidays_file="config/holidays.json"):
        self.holidays = self._load_holidays(holidays_file)

    def _load_holidays(self, filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                return {
                    datetime.strptime(d, "%Y-%m-%d").date()
                    for d in data.get("holidays", [])
                }
        except Exception as e:
            print(f"⚠️ Failed to load holidays: {e}")
            return set()

    def is_working_day(self, day):
        return day.weekday() < 5 and day not in self.holidays

    def calculate_working_days(self, start_date, end_date=None):
        if isinstance(start_date, datetime):
            start_date = start_date.date()

        if end_date is None:
            end_date = datetime.now().date()
        elif isinstance(end_date, datetime):
            end_date = end_date.date()

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        days = 0
        current = start_date

        while current <= end_date:
            if self.is_working_day(current):
                days += 1
            current += timedelta(days=1)

        return days


# ======================================================
# ClickUp Integration
# ======================================================
class ClickUpIntegration:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self, api_token, required_tag):
        self.headers = {
            "Authorization": api_token,
            "Content-Type": "application/json"
        }
        self.calculator = WorkingDaysCalculator()

        # Decode %23new → #new → new
        decoded = urllib.parse.unquote(required_tag)
        self.required_tag = decoded.lstrip("#").lower()

    def get_tasks(self, list_id):
        url = f"{self.BASE_URL}/list/{list_id}/task"
        params = {"include_closed": "true", "subtasks": "true"}

        try:
            res = requests.get(url, headers=self.headers, params=params)
            res.raise_for_status()
            return res.json().get("tasks", [])
        except Exception as e:
            print(f"❌ Error fetching tasks: {e}")
            return []

    def update_custom_field(self, task_id, field_id, value):
        url = f"{self.BASE_URL}/task/{task_id}/field/{field_id}"
        payload = {"value": value}

        try:
            res = requests.post(url, headers=self.headers, json=payload)
            res.raise_for_status()
            return True
        except Exception as e:
            print(f"❌ Failed updating task {task_id}: {e}")
            return False

    def get_custom_field_value_by_id(self, task, field_id):
        for field in task.get("custom_fields", []):
            if field.get("id") == field_id:
                value = field.get("value")
                if value and field.get("type") == "date":
                    return datetime.fromtimestamp(int(value) / 1000)
                return value
        return None

    def has_required_tag(self, task):
        for tag in task.get("tags", []):
            tag_name = tag.get("name", "").lower().lstrip("#")
            if tag_name == self.required_tag:
                return True
        return False

    def calculate_and_update_aging(self, list_id, kickoff_field_id, aging_field_id):
        tasks = self.get_tasks(list_id)

        updated, skipped = 0, 0

        for task in tasks:
            if not self.has_required_tag(task):
                continue

            task_id = task.get("id")
            name = task.get("name")

            kickoff_date = self.get_custom_field_value_by_id(
                task, kickoff_field_id
            )

            if not kickoff_date:
                print(f"⊘ Skipped: {name} (No kickoff date)")
                skipped += 1
                continue

            closed_date = None
            if task.get("date_closed"):
                closed_date = datetime.fromtimestamp(
                    int(task["date_closed"]) / 1000
                )

            aging_days = self.calculator.calculate_working_days(
                kickoff_date, closed_date
            )

            # TEXT FIELD → MUST BE STRING
            if self.update_custom_field(
                task_id, aging_field_id, str(aging_days)
            ):
                status = "Closed" if closed_date else "Open"
                print(f"✓ {name} [{status}] → Aging: {aging_days}")
                updated += 1
            else:
                skipped += 1

        print("\n" + "=" * 60)
        print(f"Summary: {updated} updated | {skipped} skipped")
        print("=" * 60)

        print("\n🔎 DEBUG: Tags found in tasks")
        for task in tasks:
            if task.get("tags"):
                print(
                    task.get("name"),
                    "→",
                    [tag.get("name") for tag in task.get("tags")]
                )


# ======================================================
# Config Loader
# ======================================================
def load_clickup_config(path="config/clickup_config.json"):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Failed to load ClickUp config: {e}")
        sys.exit(1)


# ======================================================
# MAIN
# ======================================================
def main():
    config = load_clickup_config()

    clickup = ClickUpIntegration(
        api_token=config["api_token"],
        required_tag=config["required_tag"]
    )

    clickup.calculate_and_update_aging(
        list_id=config["list_id"],
        kickoff_field_id=config["kickoff_field_id"],
        aging_field_id=config["aging_field_id"]
    )


if __name__ == "__main__":
    main()
