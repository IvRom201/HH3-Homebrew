#!/usr/bin/env python3
"""
Patch HH3 New Recruit data so the Orks catalogue participates in the normal
Crusade parent/child force system.

Run this from the repository root (the directory containing both files):
    python patch_orks_detachments.py

It patches:
  * Horus Heresy 3rd Edition.json
      - makes all generic "Visible to all factions" Crusade detachments visible to Orks
      - installs the five Ork-specific Apex/Auxiliary detachments as children of the
        Crusade Force Organization Chart
  * Orks.json
      - removes the obsolete catalogue-root forceEntries
      - gives all Ork High Command units the core High Command Detachment Choice
      - enforces the source-only unit restrictions in Deffwing / Dread Mob / Kult of Speed
        by hiding invalid Ork root entries inside those forces

The script is idempotent and makes .bak copies before writing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

GST_PATH = Path("Horus Heresy 3rd Edition.json")
ORKS_PATH = Path("Orks.json")

# Core HH3 IDs (stable in the current HH3 GST)
POINTS = "9893-c379-920b-8982"
ASSET_POINTS = "57e3-1031-7d4d-5ae3"
REACTION_POINTS = "c9ba-097e-c47f-ecc2"
AUX_COST = "3e8e-05ee-be52-12d6"
APEX_COST = "159d-855c-533d-f592"
HIGH_COMMAND_CHOICE = "969e-8b5b-1410-cfc6"
DETACHMENT_PROFILE = "7c4f-ca47-b489-3125"
DETACHMENT_COMPOSITION = "ec3f-877b-f887-18b2"


def hid(seed: str) -> str:
    h = hashlib.sha1(("hh3-orks-detachments:" + seed).encode("utf-8")).hexdigest()[:16]
    return "-".join(h[i:i+4] for i in range(0, 16, 4))


def load(path: Path):
    if not path.exists():
        raise SystemExit(f"ERROR: {path} not found. Run this script from the repository root.")
    return json.loads(path.read_text(encoding="utf-8"))


def backup(path: Path):
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)


def walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def find_by_name(items, name):
    for x in items:
        if isinstance(x, dict) and x.get("name") == name:
            return x
    return None


def faction_pair(catalogue_id: str):
    return {
        "comment": "Orks",
        "type": "and",
        "conditions": [
            {
                "childId": catalogue_id,
                "field": "selections",
                "scope": "primary-catalogue",
                "shared": True,
                "type": "instanceOf",
                "value": 1,
            },
            {
                "childId": catalogue_id,
                "field": "selections",
                "scope": "parent",
                "shared": True,
                "type": "instanceOf",
                "value": 1,
            },
        ],
    }


def patch_visible_to_all_factions(gs: dict, catalogue_id: str) -> int:
    """Append Orks to every core modifier explicitly marked Visible to all factions."""
    changed = 0
    for d in walk_dicts(gs):
        if not (d.get("comment") == "Visible to all factions" and d.get("field") == "hidden" and d.get("value") is False):
            continue

        # Do not duplicate if the Orks catalogue is already referenced anywhere in this modifier.
        if any(x.get("childId") == catalogue_id for x in walk_dicts(d)):
            continue

        cgs = d.setdefault("conditionGroups", [])
        or_group = next((g for g in cgs if isinstance(g, dict) and g.get("type") == "or"), None)
        if or_group is None:
            or_group = {"type": "or", "conditionGroups": []}
            cgs.append(or_group)
        or_group.setdefault("conditionGroups", []).append(faction_pair(catalogue_id))
        changed += 1
    return changed


def core_category_ids(gs_root: dict) -> dict[str, str]:
    out = {}
    for c in gs_root.get("categoryEntries", []):
        n, i = c.get("name"), c.get("id")
        if n and i:
            out[n] = i
    return out


def make_slot(force_name: str, slot_name: str, category_id: str, max_value: int):
    return {
        "name": slot_name,
        "id": hid(f"{force_name}:slot:{slot_name}"),
        "hidden": False,
        "targetId": category_id,
        "constraints": [
            {
                "id": hid(f"{force_name}:slot:{slot_name}:max"),
                "field": "selections",
                "scope": "parent",
                "shared": True,
                "type": "max",
                "value": max_value,
            }
        ],
    }


def ork_visibility_modifier(catalogue_id: str, required_unit_id: str | None = None):
    mod = {
        "comment": "Orks only",
        "field": "hidden",
        "type": "set",
        "value": False,
        "conditionGroups": [faction_pair(catalogue_id)],
    }
    if required_unit_id:
        mod["conditions"] = [
            {
                "childId": required_unit_id,
                "field": "selections",
                "includeChildForces": True,
                "includeChildSelections": True,
                "scope": "roster",
                "shared": True,
                "type": "atLeast",
                "value": 1,
            }
        ]
    return mod


def make_force(name: str, sort_index: int, description: str, slots, cat_ids: dict[str, str], catalogue_id: str,
               kind: str, required_unit_id: str | None = None):
    category_links = []
    for slot_name, count in slots:
        if slot_name not in cat_ids:
            raise SystemExit(f"ERROR: GST has no category named {slot_name!r}; cannot create {name}.")
        category_links.append(make_slot(name, slot_name, cat_ids[slot_name], count))

    return {
        "name": name,
        "id": hid("force:" + name),
        "hidden": True,
        "sortIndex": sort_index,
        "categoryLinks": category_links,
        "costs": [
            {"name": "Point(s)", "typeId": POINTS, "value": 0},
            {"name": "Asset Point(s)", "typeId": ASSET_POINTS, "value": 0},
            {"name": "Reaction Point(s)", "typeId": REACTION_POINTS, "value": 0},
            {"name": "Auxiliary Detachment(s)", "typeId": AUX_COST, "value": 1 if kind == "Auxiliary" else 0},
            {"name": "Apex Detachment(s)", "typeId": APEX_COST, "value": 1 if kind == "Apex" else 0},
        ],
        "modifiers": [ork_visibility_modifier(catalogue_id, required_unit_id)],
        "profiles": [
            {
                "name": name,
                "id": hid("profile:" + name),
                "hidden": False,
                "typeId": DETACHMENT_PROFILE,
                "typeName": "Detachment Description",
                "characteristics": [
                    {
                        "name": "Detachment Composition",
                        "$text": description,
                        "typeId": DETACHMENT_COMPOSITION,
                    }
                ],
            }
        ],
    }


def get_crusade_force(gs_root: dict):
    for f in gs_root.get("forceEntries", []):
        if f.get("name") == "Crusade Force Organization Chart":
            return f
    raise SystemExit("ERROR: Could not find 'Crusade Force Organization Chart' in the GST.")


def get_unit_id(cat: dict, name: str) -> str:
    for u in cat.get("sharedSelectionEntries", []):
        if u.get("name") == name and u.get("type") == "unit":
            return u["id"]
    raise SystemExit(f"ERROR: Could not find Ork unit {name!r} in Orks.json")


def add_high_command_choice(cat: dict) -> int:
    changed = 0
    high_command_targets = set()
    # Determine High Command units from root links instead of hardcoding names.
    for link in cat.get("entryLinks", []):
        cats = link.get("categoryLinks", [])
        if any(c.get("targetId") == "d9a6-9b5f-b18a-4d63" and c.get("primary") for c in cats):
            if link.get("targetId"):
                high_command_targets.add(link["targetId"])

    for u in cat.get("sharedSelectionEntries", []):
        if u.get("id") not in high_command_targets:
            continue
        links = u.setdefault("entryLinks", [])
        if any(x.get("targetId") == HIGH_COMMAND_CHOICE for x in links):
            continue
        links.append({
            "name": "High Command Detachment Choice",
            "id": hid("high-command-choice:" + u.get("name", u["id"])),
            "hidden": False,
            "import": True,
            "sortIndex": 99,
            "targetId": HIGH_COMMAND_CHOICE,
            "type": "selectionEntryGroup",
        })
        changed += 1
    return changed


def add_hide_modifier(link: dict, force_id: str, reason: str):
    mods = link.setdefault("modifiers", [])
    # idempotency marker via comment
    if any(m.get("comment") == reason for m in mods):
        return False
    mods.append({
        "comment": reason,
        "field": "hidden",
        "type": "set",
        "value": True,
        "conditions": [
            {
                "childId": force_id,
                "field": "forces",
                "includeChildForces": False,
                "includeChildSelections": False,
                "scope": "ancestor",
                "shared": True,
                "type": "instanceOf",
                "value": 1,
            }
        ],
    })
    return True


def enforce_restricted_slots(cat: dict, force_ids: dict[str, str]) -> int:
    """
    Keep standard categories, but hide entries that the source explicitly forbids
    when they are viewed inside the restricted Ork detachments. This also continues
    to work if a selected unit is later converted to a Prime slot.
    """
    changed = 0
    restrictions = [
        ("Apex - Deffwing", "3235-bd79-e9b1-60fa", "Meganobz Mob"),
        ("Apex - Dread Mob", "345f-9ba6-9b02-ed5c", "Killa Kan Mob"),
        ("Auxiliary - Kult of Speed", "2b65-a3f2-620a-dc58", "Deffkoptas"),
    ]
    for force_name, role_id, allowed_name in restrictions:
        fid = force_ids[force_name]
        for link in cat.get("entryLinks", []):
            is_role = any(c.get("primary") and c.get("targetId") == role_id for c in link.get("categoryLinks", []))
            if not is_role or link.get("name") == allowed_name:
                continue
            if add_hide_modifier(link, fid, f"Orks restriction: {force_name} allows only {allowed_name}"):
                changed += 1
    return changed


def install_ork_forces(gs_root: dict, cat: dict, catalogue_id: str):
    crusade = get_crusade_force(gs_root)
    child_forces = crusade.setdefault("forceEntries", [])
    cat_ids = core_category_ids(gs_root)

    mega_warboss = get_unit_id(cat, "Mega Warboss")
    meka_dread = get_unit_id(cat, "Kustom Meka-dread")
    big_mek = get_unit_id(cat, "Big Mek")

    # In a "3 slots, first Prime" formation, two are ordinary slots and one is
    # the corresponding Prime battlefield-role category. This makes the total 3
    # while reserving one of those slots for a Prime unit.
    specs = [
        ("Apex - Deffwing", 80, "3 Heavy Assault (1 Prime)\nHeavy Assault slots may only select Meganobz Mob.\nRequires a Mega Warboss in a High Command slot.",
         [("Heavy Assault", 2), ("Prime Heavy Assault", 1)], "Apex", mega_warboss),
        ("Apex - Dread Mob", 81, "4 War-engine (1 Prime)\n2 Support\nSupport slots may only select Killa Kan Mob.\nRequires a Kustom Meka-dread in a High Command slot.",
         [("War-engine", 3), ("Prime War-engine", 1), ("Support", 2)], "Apex", meka_dread),
        ("Auxiliary - Boss’s Bodyguard", 82, "1 Retinue\n1 Elites\n1 Heavy Transport",
         [("Retinue", 1), ("Elites", 1), ("Heavy Transport", 1)], "Auxiliary", None),
        ("Auxiliary - Green Tide", 83, "3 Troops (1 Prime)\n3 Support (1 Prime)",
         [("Troops", 2), ("Prime Troops", 1), ("Support", 2), ("Prime Support", 1)], "Auxiliary", None),
        ("Auxiliary - Kult of Speed", 84, "2 Fast Attack (1 Prime)\n1 Heavy Transport\n1 Recon\nRecon slot may only select Deffkoptas.\nRequires a Big Mek (including a Big Mek on Warbike) in a Command slot; Mega Big Mek does not qualify.",
         [("Fast Attack", 1), ("Prime Fast Attack", 1), ("Heavy Transport", 1), ("Recon", 1)], "Auxiliary", big_mek),
    ]

    names = {x[0] for x in specs}
    # Remove earlier/broken copies by name before inserting the canonical patched versions.
    child_forces[:] = [f for f in child_forces if f.get("name") not in names]

    installed = []
    for name, sort_i, desc, slots, kind, required in specs:
        f = make_force(name, sort_i, desc, slots, cat_ids, catalogue_id, kind, required)
        child_forces.append(f)
        installed.append(f)
    return installed


def validate_unique_ids(doc, label: str):
    ids = {}
    dups = []
    for d in walk_dicts(doc):
        i = d.get("id")
        if not i:
            continue
        if i in ids:
            dups.append((i, ids[i], d.get("name")))
        else:
            ids[i] = d.get("name")
    if dups:
        sample = ", ".join(x[0] for x in dups[:5])
        raise SystemExit(f"ERROR: duplicate IDs after patching {label}: {sample}")
    return len(ids)


def main():
    gst_doc = load(GST_PATH)
    ork_doc = load(ORKS_PATH)
    gs = gst_doc.get("gameSystem")
    cat = ork_doc.get("catalogue")
    if not gs or not cat:
        raise SystemExit("ERROR: unexpected JSON root structure.")

    catalogue_id = cat["id"]

    backup(GST_PATH)
    backup(ORKS_PATH)

    # The first generator incorrectly put child detachments in catalogue.forceEntries.
    # Child detachments belong under the GST Crusade force.
    old_forces = len(cat.get("forceEntries", []))
    cat["forceEntries"] = []

    visible_count = patch_visible_to_all_factions(gs, catalogue_id)
    hc_count = add_high_command_choice(cat)
    installed = install_ork_forces(gs, cat, catalogue_id)
    force_ids = {f["name"]: f["id"] for f in installed}
    restricted_count = enforce_restricted_slots(cat, force_ids)

    # Bump local revisions so New Recruit notices the changed data.
    cat["revision"] = int(cat.get("revision", 0)) + 1
    gs["revision"] = int(gs.get("revision", 0)) + 1

    gst_ids = validate_unique_ids(gst_doc, GST_PATH.name)
    ork_ids = validate_unique_ids(ork_doc, ORKS_PATH.name)

    GST_PATH.write_text(json.dumps(gst_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ORKS_PATH.write_text(json.dumps(ork_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("Orks Crusade integration patched successfully.")
    print(f"  Orks catalogue id: {catalogue_id}")
    print(f"  Generic detachments made Ork-visible: {visible_count}")
    print(f"  High Command units given Detachment Choice: {hc_count}")
    print(f"  Ork-specific child detachments installed: {len(installed)}")
    print(f"  Restricted-slot hide modifiers added: {restricted_count}")
    print(f"  Removed obsolete catalogue-root force entries: {old_forces}")
    print(f"  Unique IDs: GST={gst_ids}, Orks={ork_ids}")
    print("  Backups: *.json.bak")


if __name__ == "__main__":
    main()
