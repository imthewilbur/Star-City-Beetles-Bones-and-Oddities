#!/usr/bin/env python3
"""
Shelf update: applies one Tally form submission to shelf.json.

Input (env):
  PAYLOAD     JSON. Either {"tally": <Tally webhook body>} from Make,
              a raw Tally webhook body, or a flat dict for manual runs:
              {"action":"add|sold|remove","code":"...","name":"...","price":"...",
               "description":"...","item":"#3","photos":["https://..."]}
  SHELF_CODE  the shop code Tony types in the form (GitHub secret)

Actions:
  add     -> download + resize photos into images/shelf/, add item to the top
  sold    -> mark an item SOLD (matched by its #number or its name)
  remove  -> delete an item and its photos (for mistakes)
"""
import datetime, difflib, hmac, io, json, os, re, sys, urllib.request
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "shelf.json"
IMG_DIR = ROOT / "images" / "shelf"
MAX_PHOTOS, MAX_BYTES = 6, 25 * 1024 * 1024
FULL, SMALL = 1600, 700


def fail(msg):
    print(f"::error::{msg}")
    summary(f"❌ {msg}")
    sys.exit(1)


def summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write(text + "\n")
    print(text)


def set_output(key, value):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            f.write(f"{key}={value}\n")


# ---------------- parse the submission ----------------
def option_text(field):
    """Return the chosen option text for choice fields (Tally sends option ids)."""
    val = field.get("value")
    opts = {o.get("id"): o.get("text", "") for o in field.get("options") or []}
    if isinstance(val, list):
        return " ".join(opts.get(v, str(v)) for v in val)
    return opts.get(val, val if isinstance(val, str) else "")


def parse(payload):
    body = payload.get("tally", payload) if isinstance(payload, dict) else {}
    if isinstance(body, str):
        body = json.loads(body)
    fields = (body.get("data") or {}).get("fields")
    if not fields:  # flat manual payload
        return {k: body.get(k) for k in ("action", "code", "name", "price", "description", "item", "photos", "submission")}

    out = {"photos": [], "submission": (body.get("data") or {}).get("submissionId")}
    for f in fields:
        label, ftype, val = (f.get("label") or "").lower(), f.get("type", ""), f.get("value")
        if val in (None, "", []):
            continue
        if ftype == "FILE_UPLOAD":
            out["photos"] += [x.get("url") for x in val if isinstance(x, dict) and x.get("url")]
        elif ftype in ("MULTIPLE_CHOICE", "DROPDOWN", "MULTI_SELECT", "RANKING") or f.get("options"):
            if "action" not in out:
                out["action"] = option_text(f)
        elif "code" in label:
            out["code"] = str(val)
        elif "price" in label:
            out["price"] = val
        elif "description" in label or "details" in label:
            out["description"] = str(val)
        elif "which" in label or "number" in label or "sold" in label or "remove" in label:
            out["item"] = str(val)
        elif "name" in label or "title" in label:
            out["name"] = str(val)
    return out


def norm_action(a):
    a = (a or "").lower()
    if "sold" in a:
        return "sold"
    if "remove" in a or "delete" in a:
        return "remove"
    if "add" in a or "new" in a or "list" in a:
        return "add"
    return None


def norm_price(p):
    if p is None or str(p).strip() == "":
        return None
    s = str(p).strip()
    m = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", s)
    if not m:
        return s[:40]  # e.g. "Make an offer"
    n = float(m.group(1).replace(",", ""))
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


# ---------------- photos ----------------
def fetch(url):
    if not re.match(r"^https://", url or ""):
        raise ValueError("photo link is not https")
    req = urllib.request.Request(url, headers={"User-Agent": "StarCityBeetles-ShelfBot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("photo is over 25 MB")
    return data


def save_photo(raw, stem):
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im).convert("RGB")
    full = im.copy(); full.thumbnail((FULL, FULL), Image.LANCZOS)
    small = im.copy(); small.thumbnail((SMALL, SMALL), Image.LANCZOS)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    full.save(IMG_DIR / f"{stem}.jpg", "JPEG", quality=82, optimize=True, progressive=True)
    small.save(IMG_DIR / f"{stem}-sm.jpg", "JPEG", quality=78, optimize=True, progressive=True)
    return f"images/shelf/{stem}.jpg", f"images/shelf/{stem}-sm.jpg"


# ---------------- find an existing item ----------------
def find(items, ref, prefer_status=None):
    ref = (ref or "").strip()
    if not ref:
        return None, "Tell us which item (its #number from the website, or its name)."
    m = re.match(r"^\s*#?\s*0*(\d{1,4})\b", ref)
    if m:
        hit = [i for i in items if i["id"] == int(m.group(1))]
        if hit:
            return hit[0], None
    key = re.sub(r"[^a-z0-9 ]", "", ref.lower()).strip()
    names = {i["id"]: re.sub(r"[^a-z0-9 ]", "", i["name"].lower()).strip() for i in items}
    exact = [i for i in items if names[i["id"]] == key]
    if len(exact) == 1:
        return exact[0], None
    part = [i for i in items if key and (key in names[i["id"]] or names[i["id"]] in key)]
    if prefer_status:
        part = [i for i in part if i.get("status") == prefer_status] or part
    if len(part) == 1:
        return part[0], None
    if len(part) > 1:
        return None, f"'{ref}' matches more than one item ({', '.join('#%02d %s' % (i['id'], i['name']) for i in part)}). Use the #number."
    close = difflib.get_close_matches(key, list(names.values()), n=1, cutoff=0.72)
    if close:
        return next(i for i in items if names[i["id"]] == close[0]), None
    return None, f"Couldn't find an item matching '{ref}'."


# ---------------- main ----------------
def main():
    try:
        payload = json.loads(os.environ.get("PAYLOAD") or "{}")
    except json.JSONDecodeError:
        fail("Submission data was not valid JSON.")
    sub = parse(payload)

    expected = (os.environ.get("SHELF_CODE") or "").strip().lower()
    given = str(sub.get("code") or "").strip().lower()
    if not expected:
        fail("SHELF_CODE secret is not set in the repo, so submissions are blocked.")
    if not hmac.compare_digest(expected, given):
        fail("Wrong or missing shop code. Submission ignored.")

    action = norm_action(sub.get("action"))
    if not action:
        fail(f"Unknown action: {sub.get('action')!r}")

    data = json.loads(DATA.read_text()) if DATA.exists() else {"items": []}
    items = data.setdefault("items", [])
    seen = data.setdefault("processed", [])
    if sub.get("submission") and sub["submission"] in seen:
        summary(f"Submission {sub['submission']} was already applied. Nothing to do.")
        set_output("changed", "false")
        return
    today = datetime.date.today().isoformat()

    if action == "add":
        name = (sub.get("name") or "").strip()[:80]
        if not name:
            fail("New items need a name.")
        photos = [u for u in (sub.get("photos") or []) if u][:MAX_PHOTOS]
        if not photos:
            fail("New items need at least one photo.")
        new_id = max([i["id"] for i in items] + [int(data.get("nextId") or 1) - 1, 0]) + 1
        data["nextId"] = new_id + 1  # numbers are never reused, even after a removal
        full, small = [], []
        for n, url in enumerate(photos, 1):
            try:
                f, s = save_photo(fetch(url), f"{new_id:03d}-{n}")
                full.append(f); small.append(s)
            except Exception as e:  # keep going if one photo is bad
                print(f"::warning::Photo {n} skipped: {e}")
        if not full:
            fail("None of the photos could be downloaded or opened.")
        item = {"id": new_id, "name": name, "description": (sub.get("description") or "").strip()[:700] or None,
                "price": norm_price(sub.get("price")), "photos": full, "thumbs": small,
                "status": "available", "added": today, "soldDate": None}
        items.insert(0, item)
        msg = f"Shelf: add #{new_id:02d} {name}"
    else:
        item, err = find(items, sub.get("item") or sub.get("name"), "available" if action == "sold" else None)
        if not item:
            fail(err)
        if action == "sold":
            if item.get("status") == "sold":
                summary(f"#{item['id']:02d} {item['name']} was already marked sold.")
            item["status"], item["soldDate"] = "sold", today
            msg = f"Shelf: mark #{item['id']:02d} {item['name']} SOLD"
        else:
            for p in (item.get("photos") or []) + (item.get("thumbs") or []):
                fp = ROOT / p
                if fp.is_file() and fp.resolve().parent == IMG_DIR.resolve():
                    fp.unlink()
            items.remove(item)
            msg = f"Shelf: remove #{item['id']:02d} {item['name']}"

    if sub.get("submission"):
        seen.append(sub["submission"])
        data["processed"] = seen[-200:]
    data["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    summary(f"✅ {msg}")
    set_output("changed", "true")
    set_output("message", msg.replace("\n", " "))


if __name__ == "__main__":
    main()
