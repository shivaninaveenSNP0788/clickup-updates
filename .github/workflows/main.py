import requests
import json
from datetime import datetime, timedelta

# ============================
# CONFIGURATION - FULLY CONFIGURED
# ============================
API_TOKEN = "pk_218696006_UXYXEI6AKDLMXJ3P4INX79SD9ZO0UTF0"
# LIST_ID = "901413543284" ----- NEW LIST
LIST_ID = "901412176234" # ----- ONBOARDING

# 🛑 FIXED: Use the tag name only ("new") for the filter 🛑
TAG_FILTER = "%23new"

# Custom Field ID for the Platform Dropdown
FIELD_COMMERCE_PLATFORM = "4927273a-9c1f-4042-8aca-5fd4d14fa26a"

# Custom Field IDs for the DATE fields
FIELD_KICKOFF     = "7c302bd2-027a-4f17-b795-c3f55a044868"
FIELD_DESIGN      = "8425e4a9-2dc3-4064-88ce-629706717aab"
FIELD_INTEGRATION = "ed0a3f9a-824d-40cd-9b43-4fb72e1876f4"
FIELD_PREGOLIVE   = "afc4d2a9-4a58-4038-b96d-248a7c7d765e"
FIELD_QA          = "59bfc489-64c2-402a-bf35-865116d22af5"
FIELD_GOLIVE      = "7344338c-1889-443b-b698-9924c9c936f2"

# --- API Setup ---
headers = {"Authorization": API_TOKEN}

# Global maps for index-based lookup
PLATFORM_UUID_TO_NAME = {}
PLATFORM_ID_BY_INDEX = []

# ============================
# DATE OFFSETS CONFIGURATION
# ============================
DATE_OFFSETS = {
    "shopify": {"Kickoff": 2, "Design": 4, "Integration": 6, "PreGoLive": 7, "QA": 8, "GoLive": 9},
    "rich": {"Kickoff": 2, "Design": 5, "Integration": 7, "PreGoLive": 16, "QA": 20, "GoLive": 21},
    "custom": {"Kickoff": 2, "Design": 6, "Integration": 8, "PreGoLive": 30, "QA": 34, "GoLive": 35}
}

FIELD_MAP = {
    "Kickoff": FIELD_KICKOFF, "Design": FIELD_DESIGN, "Integration": FIELD_INTEGRATION,
    "PreGoLive": FIELD_PREGOLIVE, "QA": FIELD_QA, "GoLive": FIELD_GOLIVE
}

RICH_PLATFORMS = ["woocommerce", "woo commerce", "woo", "magento", "sfcc", "salesforce", "bigcommerce", "big commerce"]

# ============================
# HELPER FUNCTIONS
# ============================

def add_calendar_days(start_ms, days):
    """Adds a fixed number of calendar days to a starting timestamp."""
    date = datetime.fromtimestamp(start_ms / 1000)
    date += timedelta(days=days)
    return int(date.timestamp() * 1000)

def add_workdays(start_ms, days):
    """Adds a fixed number of working days (Mon-Fri) to a starting timestamp."""
    date = datetime.fromtimestamp(start_ms / 1000)
    one = timedelta(days=1)
    while days > 0:
        date += one
        if date.weekday() < 5:
            days -= 1
    return int(date.timestamp() * 1000)

def fetch_field_options(list_id, field_id):
    """Fetches the drop-down options, mapping by both UUID and Index."""
    url = f"https://api.clickup.com/api/v2/list/{list_id}/field"
    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        print(f"❌ Error fetching field definitions: {r.text}")
        return False

    data = r.json()
    field_def = next((f for f in data.get('fields', []) if f['id'] == field_id), None)

    if not field_def or field_def.get('type') != 'drop_down':
        print(f"❌ Could not find drop_down field with ID {field_id}.")
        return False

    global PLATFORM_UUID_TO_NAME, PLATFORM_ID_BY_INDEX

    # 1. Populate PLATFORM_UUID_TO_NAME (UUID -> Name)
    PLATFORM_UUID_TO_NAME = {option['id']: option['name'] for option in field_def['type_config']['options']}

    # 2. Populate PLATFORM_ID_BY_INDEX (Index -> UUID list, based on 'orderindex')
    sorted_options = sorted(field_def['type_config']['options'], key=lambda x: x['orderindex'])
    PLATFORM_ID_BY_INDEX = [option['id'] for option in sorted_options]

    print(f"✅ Fetched {len(PLATFORM_UUID_TO_NAME)} platform options.")
    return True

def get_all_tasks(list_id):
    """Paginates through and retrieves all tasks from the list, now filtered by Tag."""
    tasks = []
    page = 0

    while True:
        # URL construction with the raw tag name
        url = f"https://api.clickup.com/api/v2/list/{list_id}/task?page={page}&tags[]={TAG_FILTER}"
        r = requests.get(url, headers=headers)
        data = r.json()
        if "tasks" not in data or not data["tasks"]:
            break
        tasks.extend(data["tasks"])
        page += 1

    print(f"Filtering for Tag: #{TAG_FILTER}")
    return tasks

def classify_platform(option_uuid):
    """Maps a platform UUID to 'shopify', 'rich', or 'custom' based on name."""
    if not option_uuid:
        return "custom"

    value = PLATFORM_UUID_TO_NAME.get(option_uuid)

    if not value:
        return "custom"

    v = value.lower()

    if "shopify" in v:
        return "shopify"

    if any(p in v for p in RICH_PLATFORMS):
        return "rich"

    return "custom"

# ============================
# MAIN EXECUTION
# ============================

def run_update_script():
    if not fetch_field_options(LIST_ID, FIELD_COMMERCE_PLATFORM):
        print("\nScript aborted due to failure in fetching platform field options.")
        return

    tasks = get_all_tasks(LIST_ID)
    if not tasks:
        print("No tasks found to process.")
        return

    print(f"Found {len(tasks)} tasks to process.\n")
    updated_count = 0
    skipped_count = 0 # Counter for skipped tasks

    for task in tasks:
        task_id = task["id"]
        update_successful = True

        date_created = task.get("date_created")
        try:
            date_created = int(date_created)
        except (TypeError, ValueError):
            print(f"[WARN] Skipping task {task_id} - cannot parse date_created: {task.get('date_created')}")
            continue

        platform_id = None # This will hold the UUID
        platform_name = "N/A"

        # 1. Try to extract the platform_id
        for f in task.get("custom_fields", []):
            if f["id"] == FIELD_COMMERCE_PLATFORM:
                raw_value = f.get("value")

                if isinstance(raw_value, int):
                    try:
                        platform_id = PLATFORM_ID_BY_INDEX[raw_value]
                    except IndexError:
                        print(f"❌ [ERROR] Task {task_id}: Invalid index {raw_value} for platform field.")
                        platform_id = None
                elif isinstance(raw_value, list) and raw_value:
                    platform_id = raw_value[0]
                elif isinstance(raw_value, str) and raw_value:
                    platform_id = raw_value

                if platform_id:
                    platform_name = PLATFORM_UUID_TO_NAME.get(platform_id, "Custom")
                break

        # 🛑 MODIFICATION: Skip if platform_id is null (not set) 🛑
        if not platform_id:
            print(f"[SKIP] Task {task_id}: Commerce Platform field is NULL. Skipping date calculations.")
            skipped_count += 1
            continue

        group = classify_platform(platform_id)

        successful_updates = []

        # 3. Calculate and update all dates
        for stage_name, field_id in FIELD_MAP.items():

            offsets = DATE_OFFSETS.get(group, DATE_OFFSETS["custom"]) # Fallback to custom if group is bad
            days_offset = offsets.get(stage_name)

            start_ms = date_created
            calculator = add_workdays

            is_calendar_day_stage = group in ["rich", "custom"] and stage_name in ["PreGoLive", "QA", "GoLive"]

            if is_calendar_day_stage:
                calculator = add_calendar_days

            if days_offset is not None:
                target_timestamp = calculator(start_ms, days_offset)
            else:
                update_successful = False
                continue

            # 4. Prepare and execute the API update
            payload = { "value_options": { "time": True }, "value": target_timestamp }

            url = f"https://api.clickup.com/api/v2/task/{task_id}/field/{field_id}"
            r = requests.post(url, json=payload, headers=headers)

            if r.status_code == 200:
                successful_updates.append(stage_name)
            else:
                print(f"❌ Error updating {stage_name} ({field_id}) for {task_id}. Platform: {platform_name}. Response: {r.text[:100]}...")
                update_successful = False

        # 5. Logging result
        if update_successful:
            print(f"✅ Updated {task_id} | Platform: **{platform_name}** ({group}) | Stages: {', '.join(successful_updates)}")
            updated_count += 1
        elif successful_updates:
            print(f"⚠️ Partially updated {task_id} | Stages successful: {', '.join(successful_updates)}")

    print(f"\n=================================")
    print(f"DONE — {updated_count} tasks successfully updated.")
    print(f"{skipped_count} tasks skipped (Null Platform).")
    print(f"=================================")

if __name__ == "__main__":
    run_update_script()