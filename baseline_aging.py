import requests
import json
import os

# ============================
# LOAD CONFIG
# ============================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "clickup_config.json")

with open(CONFIG_PATH, "r") as f:
    cfg = json.load(f)

API_TOKEN = cfg["api_token"]
LIST_ID = cfg["list_id"]
FIELD_COMMERCE_PLATFORM = cfg["commerce_platform_field_id"]
FIELD_BASELINE = cfg["baseline_field_id"]
REQUIRED_TAG = cfg.get("required_tag")

HEADERS = {
    "Authorization": API_TOKEN,
    "Content-Type": "application/json"
}

# ============================
# PLATFORM LOGIC
# ============================

RICH_PLATFORMS = ["woo", "woocommerce", "magento", "sfcc", "big"]

PLATFORM_TO_BASELINE = {
    "shopify": "9d",
    "rich": "21d",
    "custom": "35d"
}

# ============================
# DROPDOWN MAPS
# ============================

PLATFORM_UUID_TO_NAME = {}
PLATFORM_ID_BY_INDEX = []
BASELINE_VALUE_TO_UUID = {}

# ============================
# CLICKUP HELPERS
# ============================

def fetch_dropdowns():
    url = f"https://api.clickup.com/api/v2/list/{LIST_ID}/field"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()

    fields = r.json().get("fields", [])

    # Commerce Platform dropdown
    platform_field = next(f for f in fields if f["id"] == FIELD_COMMERCE_PLATFORM)
    platform_opts = platform_field["type_config"]["options"]

    global PLATFORM_UUID_TO_NAME, PLATFORM_ID_BY_INDEX
    PLATFORM_UUID_TO_NAME = {o["id"]: o["name"].lower() for o in platform_opts}
    PLATFORM_ID_BY_INDEX = [o["id"] for o in sorted(platform_opts, key=lambda x: x["orderindex"])]

    # Baseline dropdown
    baseline_field = next(f for f in fields if f["id"] == FIELD_BASELINE)
    baseline_opts = baseline_field["type_config"]["options"]

    global BASELINE_VALUE_TO_UUID
    BASELINE_VALUE_TO_UUID = {
        o["name"].lower(): o["id"]
        for o in baseline_opts
    }

def get_all_tasks():
    tasks = []
    page = 0

    while True:
        url = f"https://api.clickup.com/api/v2/list/{LIST_ID}/task?page={page}&include_closed=true"
        if REQUIRED_TAG:
            url += f"&tags[]={REQUIRED_TAG}"

        r = requests.get(url, headers=HEADERS)
        data = r.json()

        if not data.get("tasks"):
            break

        tasks.extend(data["tasks"])
        page += 1

    return tasks

def resolve_platform(task):
    for f in task.get("custom_fields", []):
        if f["id"] == FIELD_COMMERCE_PLATFORM:
            raw = f.get("value")
            option_id = None

            if isinstance(raw, int) and raw < len(PLATFORM_ID_BY_INDEX):
                option_id = PLATFORM_ID_BY_INDEX[raw]
            elif isinstance(raw, str):
                option_id = raw
            elif isinstance(raw, list) and raw:
                option_id = raw[0]

            if option_id:
                name = PLATFORM_UUID_TO_NAME.get(option_id, "")
                if "shopify" in name:
                    return "shopify"
                if any(p in name for p in RICH_PLATFORMS):
                    return "rich"

    return "custom"

def get_baseline_value(task):
    for f in task.get("custom_fields", []):
        if f["id"] == FIELD_BASELINE:
            return f.get("value")
    return None

def update_baseline(task_id, baseline_uuid):
    url = f"https://api.clickup.com/api/v2/task/{task_id}/field/{FIELD_BASELINE}"
    payload = {"value": baseline_uuid}

    r = requests.post(url, headers=HEADERS, json=payload)

    if r.status_code not in (200, 204):
        print(f"❌ Failed for {task_id}: {r.text}")
        return False

    return True

# ============================
# MAIN
# ============================

def run():
    fetch_dropdowns()

    tasks = get_all_tasks()
    print(f"🔎 Processing {len(tasks)} tasks")

    updated = skipped = 0

    for task in tasks:
        task_id = task["id"]

        # Skip if baseline already set
        if get_baseline_value(task) is not None:
            skipped += 1
            continue

        platform = resolve_platform(task)
        baseline_label = PLATFORM_TO_BASELINE[platform]

        baseline_uuid = BASELINE_VALUE_TO_UUID.get(baseline_label.lower())
        if not baseline_uuid:
            print(f"⚠️ Baseline option missing in ClickUp: {baseline_label}")
            continue

        if update_baseline(task_id, baseline_uuid):
            updated += 1
            print(f"✅ {task_id} | {platform} → {baseline_label}")

    print("\n" + "=" * 60)
    print(f"Summary: {updated} updated | {skipped} skipped")
    print("=" * 60)

if __name__ == "__main__":
    run()
