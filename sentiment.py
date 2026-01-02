
import requests
import json
import os
import re
import time
import urllib.parse
from urllib.parse import unquote

# ============================
# LOAD CONFIG
# ============================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "clickup_config.json")

with open(CONFIG_PATH, "r") as f:
    cfg = json.load(f)

API_TOKEN = cfg["api_token"]
LIST_ID = cfg["list_id"]
FIELD_SENTIMENT = cfg["sentiment_field_id"]          # dropdown: sentiment - delivery
FIELD_ACTUAL = cfg["actual_aging_field_id"]          # text: actual aging
FIELD_BASELINE = cfg["baseline_field_id"]            # dropdown: baseline aging
REQUIRED_TAG = cfg.get("required_tag")               # e.g., "%23new"
DRY_RUN = bool(cfg.get("dry_run", False))
PAUSE_MS = int(cfg.get("pause_ms_between_updates", 0))

HEADERS = {
    "Authorization": API_TOKEN,
    "Content-Type": "application/json"
}

# ============================
# DROPDOWN MAPS
# ============================

# Baseline dropdown mappings
BASELINE_ID_TO_NAME = {}
BASELINE_NAME_TO_ID = {}
BASELINE_ID_TO_DAYS = {}

# Sentiment dropdown mappings
SENTIMENT_NAME_TO_ID = {}
SENTIMENT_ID_TO_NAME = {}

# Target sentiment labels expected in ClickUp dropdown
SENTIMENT_LABELS = {
    "escalated, at risk": "escalated, at risk",
    "slightly delayed": "slightly delayed",
    "on time": "on time",
    "delivered early": "delivered early",
}

# ============================
# HELPERS
# ============================

def normalize_label(s: str) -> str:
    return (s or "").strip().lower()

def normalize_tag(tag: str) -> str:
    """
    Normalize a tag into its plain form for comparison:
    Accepts raw ('new'), hashtag ('#new'), or URL-encoded ('%23new').
    Returns 'new' for any of these.
    """
    if not tag:
        return ""
    t = tag.strip()
    t = unquote(t)  # '%23new' -> '#new'
    if t.startswith("#"):
        t = t[1:]
    return t.lower()

def tag_for_api_param(tag: str) -> str:
    """
    Prepare the 'tags[]=' query param value.
    If config provides URL-encoded tag (e.g., '%23new'), pass it through as-is.
    Otherwise, encode leading '#' if present.
    """
    if not tag:
        return ""
    raw = tag.strip()
    if "%" in raw:
        return raw
    raw = unquote(raw)
    if raw.startswith("#"):
        return "%23" + raw[1:]
    return raw

def task_has_tag(task, tag_plain: str) -> bool:
    """Client-side guard: ensure the task truly has the tag (case-insensitive)."""
    if not tag_plain:
        return True
    target = normalize_tag(tag_plain)
    tags = task.get("tags", [])
    return any(normalize_tag(t.get("name", "")) == target for t in tags)

def parse_days_from_text(raw: str):
    """
    Parse 'Actual Aging' text into integer days.
    Accepts '5d', '5 d', '5 days', '5', '48h' (converted to 2 days).
    Returns int days or None if unparsable.
    """
    if raw is None:
        return None
    txt = str(raw).strip().lower()

    m = re.search(r"(-?\d+)", txt)
    if not m:
        return None
    val = int(m.group(1))

    # If hours provided without 'd/day/days', convert floor to days
    if "h" in txt and not any(u in txt for u in ["d", "day", "days"]):
        return val // 24

    return val

def parse_days_from_baseline_name(name: str):
    """
    Parse baseline dropdown option name (e.g., '9d', '21d') to integer days.
    Returns int days or None.
    """
    if not name:
        return None
    m = re.search(r"(-?\d+)", name.strip().lower())
    return int(m.group(1)) if m else None

def resolve_dropdown_value(field_value, options):
    """
    Resolve ClickUp dropdown 'value' to an option_id.
    'value' can be int (index), str (id), or list (multi-select; take first).
    """
    if field_value is None:
        return None

    if isinstance(field_value, int):
        sorted_opts = [o["id"] for o in sorted(options, key=lambda x: x["orderindex"])]
        if 0 <= field_value < len(sorted_opts):
            return sorted_opts[field_value]
        return None
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list) and field_value:
        return field_value[0]
    return None

# ============================
# CLICKUP HELPERS
# ============================

def fetch_dropdowns():
    """
    Fetch list fields and initialize baseline & sentiment dropdown maps.
    """
    url = f"https://api.clickup.com/api/v2/list/{LIST_ID}/field"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()

    fields = r.json().get("fields", [])

    # Baseline dropdown
    baseline_field = next((f for f in fields if f["id"] == FIELD_BASELINE), None)
    if not baseline_field:
        raise RuntimeError(f"Baseline field id not found: {FIELD_BASELINE}")
    baseline_opts = baseline_field["type_config"]["options"]
    for o in baseline_opts:
        oid = o["id"]
        name = o["name"]
        BASELINE_ID_TO_NAME[oid] = name
        BASELINE_NAME_TO_ID[normalize_label(name)] = oid
        BASELINE_ID_TO_DAYS[oid] = parse_days_from_baseline_name(name)

    # Sentiment dropdown
    sentiment_field = next((f for f in fields if f["id"] == FIELD_SENTIMENT), None)
    if not sentiment_field:
        raise RuntimeError(f"Sentiment field id not found: {FIELD_SENTIMENT}")
    sentiment_opts = sentiment_field["type_config"]["options"]
    for o in sentiment_opts:
        oid = o["id"]
        name = o["name"]
        SENTIMENT_ID_TO_NAME[oid] = name
        SENTIMENT_NAME_TO_ID[normalize_label(name)] = oid

    # Validate required sentiment labels exist
    missing = [
        lbl for lbl in SENTIMENT_LABELS.values()
        if normalize_label(lbl) not in SENTIMENT_NAME_TO_ID
    ]
    if missing:
        print("⚠️ Missing sentiment dropdown options in ClickUp:", missing)
        print("   Please add these options or adjust SENTIMENT_LABELS to match your field.")
    else:
        print("✅ Sentiment dropdown options resolved.")

def get_all_tasks():
    """
    Fetch tasks from the list, filtered server-side:
      - tag == '#new' (config as '%23new')
      - Actual Aging IS NOT NULL
      - Baseline Aging IS NOT NULL
    Uses pagination until no more tasks.
    """
    tasks = []
    page = 0

    tag_param = tag_for_api_param(REQUIRED_TAG) if REQUIRED_TAG else None

    # Build the custom_fields filter array and stringify for query param
    cf_filters = [
        {"field_id": FIELD_ACTUAL,   "operator": "IS NOT NULL"},
        {"field_id": FIELD_BASELINE, "operator": "IS NOT NULL"},
    ]
    cf_param = urllib.parse.quote(json.dumps(cf_filters))

    while True:
        url = (
            f"https://api.clickup.com/api/v2/list/{LIST_ID}/task"
            f"?page={page}"
            f"&include_closed=true"
            f"&limit=100"
        )
        if tag_param:
            url += f"&tags[]={tag_param}"
        url += f"&custom_fields={cf_param}"

        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        data = r.json()

        page_tasks = data.get("tasks", [])
        if not page_tasks:
            break

        tasks.extend(page_tasks)
        page += 1

    return tasks

def get_field_value(task, field_id):
    for f in task.get("custom_fields", []):
        if f["id"] == field_id:
            return f.get("value"), f
    return None, None

def get_actual_days(task):
    raw_val, _ = get_field_value(task, FIELD_ACTUAL)
    return parse_days_from_text(raw_val)

def get_baseline_days(task, baseline_field_def):
    raw_val, _ = get_field_value(task, FIELD_BASELINE)
    option_id = resolve_dropdown_value(raw_val, baseline_field_def["type_config"]["options"])
    if option_id and option_id in BASELINE_ID_TO_DAYS:
        return BASELINE_ID_TO_DAYS[option_id]
    return None

def get_current_sentiment_option_id(task, sentiment_field_def):
    raw_val, _ = get_field_value(task, FIELD_SENTIMENT)
    return resolve_dropdown_value(raw_val, sentiment_field_def["type_config"]["options"])

def classify_sentiment(delta_days):
    """
    Map delta (actual - baseline) to sentiment:
      >= 5d  -> escalated, at risk
      0d<Δ<=4d -> slightly delayed
      Δ==0d -> on time
      Δ<0d  -> delivered early
    """
    if delta_days is None:
        return None
    if delta_days >= 5:
        return SENTIMENT_LABELS["escalated, at risk"]
    elif 0 < delta_days <= 4:
        return SENTIMENT_LABELS["slightly delayed"]
    elif delta_days == 0:
        return SENTIMENT_LABELS["on time"]
    elif delta_days < 0:
        return SENTIMENT_LABELS["delivered early"]
    return None

def update_dropdown(task_id, field_id, option_id):
    """
    Update a dropdown custom field value on a task.
    """
    url = f"https://api.clickup.com/api/v2/task/{task_id}/field/{field_id}"
    payload = {"value": option_id}

    if DRY_RUN:
        print(f"🔎 DRY RUN | Would update task {task_id} field {field_id} -> option {option_id}")
        return True

    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code in (200, 204):
        return True

    print(f"❌ Update failed for {task_id} ({field_id}): {r.status_code} {r.text}")
    return False

# ============================
# MAIN
# ============================

def run():
    # Fetch field definitions once (needed to resolve indices -> option ids)
    url_fields = f"https://api.clickup.com/api/v2/list/{LIST_ID}/field"
    fields_resp = requests.get(url_fields, headers=HEADERS)
    fields_resp.raise_for_status()
    list_fields = fields_resp.json().get("fields", [])

    baseline_field_def = next((f for f in list_fields if f["id"] == FIELD_BASELINE), None)
    sentiment_field_def = next((f for f in list_fields if f["id"] == FIELD_SENTIMENT), None)
    if not baseline_field_def or not sentiment_field_def:
        raise RuntimeError("Baseline or Sentiment field definitions not found in list fields.")

    fetch_dropdowns()

    tasks = get_all_tasks()
    print(f"🔎 Fetched {len(tasks)} tasks (API-side filtered by tag + custom_fields).")

    updated = skipped = missing_data = 0
    required_tag_plain = normalize_tag(REQUIRED_TAG)  # e.g., '%23new' -> 'new'

    for task in tasks:
        task_id = task["id"]

        # Client-side guard (redundant but safe if filters change upstream)
        if required_tag_plain and not task_has_tag(task, required_tag_plain):
            skipped += 1
            print(f"⛔ {task_id} skipped: missing '#{required_tag_plain}' tag")
            continue

        actual_days = get_actual_days(task)
        baseline_days = get_baseline_days(task, baseline_field_def)

        if actual_days is None or baseline_days is None:
            missing_data += 1
            print(f"⚠️ {task_id} missing/invalid data | actual={actual_days} baseline={baseline_days}")
            continue

        delta = actual_days - baseline_days
        target_label = classify_sentiment(delta)
        if not target_label:
            skipped += 1
            print(f"⚠️ {task_id} no target label for Δ={delta}d")
            continue

        target_id = SENTIMENT_NAME_TO_ID.get(normalize_label(target_label))
        if not target_id:
            skipped += 1
            print(f"⚠️ {task_id} sentiment label not found in dropdown: {target_label}")
            continue

        current_id = get_current_sentiment_option_id(task, sentiment_field_def)
        if current_id == target_id:
            skipped += 1
            print(f"⏭️ {task_id} already set: {SENTIMENT_ID_TO_NAME.get(current_id)} (Δ={delta}d)")
            continue

        ok = update_dropdown(task_id, FIELD_SENTIMENT, target_id)
        if ok:
            updated += 1
            print(f"✅ {task_id} | Δ={delta}d → {target_label}")
            if PAUSE_MS > 0:
                time.sleep(PAUSE_MS / 1000.0)
        else:
            print(f"❌ {task_id} update failed | intended {target_label} (Δ={delta}d)")

    print("\n" + "=" * 60)
    print(f"Summary: {updated} updated | {skipped} skipped | {missing_data} missing data")
    print("=" * 60)

if __name__ == "__main__":
    run()
