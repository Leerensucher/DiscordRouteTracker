"""DiscordRouteTracker EDMC plugin.

Tracks two independent route progress embeds for ship and fleet carrier jumps.
Version 1 intentionally does not include Spansh or external route planning.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - EDMC provides tkinter in normal use.
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

try:
    import myNotebook as nb  # type: ignore[import-not-found]  # noqa: N813
except Exception:  # pragma: no cover - only available inside EDMC.
    nb = None  # type: ignore[assignment]

try:
    import requests
except Exception:  # pragma: no cover - handled at runtime for users.
    requests = None  # type: ignore[assignment]


PLUGIN_NAME = "DiscordRouteTracker"
PLUGIN_VERSION = "0.1.1"
STATE_FILE = "route_state.json"
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/Leerensucher/DiscordRouteTracker/main/DiscordRouteTracker/update_manifest.json"
UPDATE_CHECK_ON_START = True
UPDATE_FILE_ALLOWLIST = {"load.py"}
TRACKER_KINDS = ("ship", "carrier")

DISPLAY_NAMES = {
    "ship": "Schiff",
    "carrier": "Carrier",
}

DEFAULT_TRACKER_STATE: Dict[str, Any] = {
    "webhook_url": "",
    "poster_name": "",
    "message_id": "",
    "messages": [],
    "start_system": "",
    "target_system": "",
    "current_system": "",
    "image_url": "",
    "jumps_done": 0,
    "distance_done": 0.0,
    "last_jump_distance": 0.0,
    "longest_jump_distance": 0.0,
    "shortest_jump_distance": 0.0,
    "last_pos": None,
    "planned_jumps": 0,
    "planned_distance": 0.0,
    "route_systems": [],
    "start_time": "",
    "end_time": "",
    "route_completed": False,
}

DEFAULT_STATE: Dict[str, Any] = {
    "ship": copy.deepcopy(DEFAULT_TRACKER_STATE),
    "carrier": copy.deepcopy(DEFAULT_TRACKER_STATE),
}
DEFAULT_STATE["autopost"] = False
DEFAULT_STATE["plugin_enabled"] = True
DEFAULT_STATE["ship"]["active_ship_name"] = ""
DEFAULT_STATE["ship"]["image_urls_by_ship"] = {}
DEFAULT_STATE["carrier"]["active_carrier_name"] = ""
DEFAULT_STATE["carrier"]["image_urls_by_carrier"] = {}

plugin_dir_path = ""
state_path = ""
state: Dict[str, Any] = copy.deepcopy(DEFAULT_STATE)
current_ship_name = ""
current_carrier_name = ""
current_cmdr_name = ""
current_system_name = ""
current_system_pos: Optional[List[float]] = None
game_running = False

status_var: Optional["tk.StringVar"] = None
status_label_widget: Optional[Any] = None
autopost_var: Optional["tk.BooleanVar"] = None
plugin_enabled_var: Optional["tk.BooleanVar"] = None
main_app_frame: Optional[Any] = None
ship_poster_name_var: Optional["tk.StringVar"] = None
ship_webhook_var: Optional["tk.StringVar"] = None
ship_target_var: Optional["tk.StringVar"] = None
ship_image_var: Optional["tk.StringVar"] = None
ship_planned_jumps_var: Optional["tk.StringVar"] = None
ship_planned_distance_var: Optional["tk.StringVar"] = None
active_ship_label_var: Optional["tk.StringVar"] = None
carrier_poster_name_var: Optional["tk.StringVar"] = None
carrier_webhook_var: Optional["tk.StringVar"] = None
carrier_target_var: Optional["tk.StringVar"] = None
carrier_image_var: Optional["tk.StringVar"] = None
carrier_planned_jumps_var: Optional["tk.StringVar"] = None
carrier_planned_distance_var: Optional["tk.StringVar"] = None
active_carrier_label_var: Optional["tk.StringVar"] = None
main_controls: List[Any] = []
send_controls: List[Any] = []
ship_send_controls: List[Any] = []
pref_controls: List[Any] = []
ship_image_mapping_vars: Dict[str, Any] = {}
carrier_image_mapping_vars: Dict[str, Any] = {}
ship_image_mapping_tree: Optional[Any] = None
carrier_image_mapping_tree: Optional[Any] = None


def plugin_start3(plugin_dir: str) -> str:
    """EDMC entry point called when the plugin is loaded."""
    global plugin_dir_path, state_path, state, current_ship_name, current_carrier_name

    plugin_dir_path = plugin_dir
    state_path = os.path.join(plugin_dir_path, STATE_FILE)
    state = load_state()
    current_ship_name = str(state["ship"].get("active_ship_name") or "")
    current_carrier_name = str(state["carrier"].get("active_carrier_name") or "")
    return PLUGIN_NAME


def plugin_app(parent: Any) -> Any:
    """Build the small control panel shown in EDMC's main window."""
    if tk is None:
        return None

    global status_var, status_label_widget, autopost_var, main_app_frame
    status_var = tk.StringVar(value="Spiel erkannt." if game_running else "Warte auf Spiel.")
    autopost_var = tk.BooleanVar(value=autopost_enabled())

    outer_frame = make_frame(parent)
    frame = make_frame(outer_frame)
    main_app_frame = frame
    frame.grid(row=0, column=0, sticky="ew")
    outer_frame.columnconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    frame.columnconfigure(1, weight=1)

    main_controls.clear()
    send_controls.clear()
    ship_send_controls.clear()
    ship_send_button = make_button(
        frame,
        text="Schiff erstellen / senden",
        command=lambda: send_initial_embed("ship"),
    )
    ship_send_button.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
    main_controls.append(ship_send_button)
    send_controls.append(ship_send_button)
    ship_send_controls.append(ship_send_button)

    carrier_send_button = make_button(
        frame,
        text="Carrier erstellen / senden",
        command=lambda: send_initial_embed("carrier"),
    )
    carrier_send_button.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
    main_controls.append(carrier_send_button)
    send_controls.append(carrier_send_button)

    ship_reset_button = make_button(
        frame,
        text="Schiff zurücksetzen",
        command=lambda: reset_tracker("ship"),
    )
    ship_reset_button.grid(row=1, column=0, sticky="ew", padx=2, pady=2)
    main_controls.append(ship_reset_button)

    carrier_reset_button = make_button(
        frame,
        text="Carrier zurücksetzen",
        command=lambda: reset_tracker("carrier"),
    )
    carrier_reset_button.grid(row=1, column=1, sticky="ew", padx=2, pady=2)
    main_controls.append(carrier_reset_button)

    action_frame = make_frame(frame)
    action_frame.columnconfigure(0, weight=1)
    action_frame.columnconfigure(1, weight=1)
    action_frame.columnconfigure(2, weight=1)
    action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=0)

    make_button(
        action_frame,
        text="Einstellungen",
        command=lambda: open_settings_dialog(parent),
    ).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
    make_button(
        action_frame,
        text="Update prüfen",
        command=lambda: check_for_updates(silent=False),
    ).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
    make_checkbutton(
        action_frame,
        text="Autopost",
        variable=autopost_var,
        command=autopost_changed,
    ).grid(row=0, column=2, sticky="w", padx=6, pady=2)
    status_label_widget = make_status_label(frame, textvariable=status_var)
    status_label_widget.grid(
        row=3, column=0, columnspan=2, sticky="w", padx=2, pady=(4, 2)
    )
    update_ui_enabled()
    if UPDATE_CHECK_ON_START:
        check_for_updates(silent=True)

    return outer_frame


def plugin_prefs(parent: Any, cmdr: str, is_beta: bool) -> Any:
    """Build the EDMC preferences panel for this plugin."""
    del cmdr, is_beta

    if tk is None:
        return None

    global ship_poster_name_var, ship_webhook_var, ship_target_var, ship_image_var
    global ship_planned_jumps_var, ship_planned_distance_var
    global active_ship_label_var
    global carrier_poster_name_var, carrier_webhook_var, carrier_target_var
    global carrier_image_var, carrier_planned_jumps_var, carrier_planned_distance_var
    global active_carrier_label_var
    global ship_image_mapping_vars, carrier_image_mapping_vars
    global ship_image_mapping_tree, carrier_image_mapping_tree
    global plugin_enabled_var

    plugin_enabled_var = tk.BooleanVar(value=plugin_enabled())
    ship_poster_name_var = tk.StringVar(value=state["ship"].get("poster_name", ""))
    ship_webhook_var = tk.StringVar(value=state["ship"].get("webhook_url", ""))
    ship_target_var = tk.StringVar(value=state["ship"].get("target_system", ""))
    ship_image_var = tk.StringVar(value=get_current_ship_image_url())
    ship_planned_jumps_var = tk.StringVar(value=planned_jumps_text("ship"))
    ship_planned_distance_var = tk.StringVar(value=planned_distance_text("ship"))
    active_ship_label_var = tk.StringVar(value=active_vehicle_text("ship"))
    carrier_poster_name_var = tk.StringVar(value=state["carrier"].get("poster_name", ""))
    carrier_webhook_var = tk.StringVar(value=state["carrier"].get("webhook_url", ""))
    carrier_target_var = tk.StringVar(value=state["carrier"].get("target_system", ""))
    carrier_image_var = tk.StringVar(value=get_current_carrier_image_url())
    carrier_planned_jumps_var = tk.StringVar(value=planned_jumps_text("carrier"))
    carrier_planned_distance_var = tk.StringVar(value=planned_distance_text("carrier"))
    active_carrier_label_var = tk.StringVar(value=active_vehicle_text("carrier"))

    frame = make_frame(parent)
    frame.columnconfigure(1, weight=1)

    make_checkbutton(
        frame,
        text="Plugin aktiv",
        variable=plugin_enabled_var,
    ).grid(row=0, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 8))

    rows = [
        ("Aktuelles Schiff", active_ship_label_var, False),
        ("Schiff Discord-Name", ship_poster_name_var),
        ("Schiff Webhook", ship_webhook_var),
        ("Schiff Zielsystem", ship_target_var),
        ("Schiff Sprünge geplant", ship_planned_jumps_var),
        ("Schiff Entfernung gesamt (ly)", ship_planned_distance_var),
        ("Schiff Bild-URL", ship_image_var),
        ("Aktueller Carrier", active_carrier_label_var, False),
        ("Carrier Discord-Name", carrier_poster_name_var),
        ("Carrier Webhook", carrier_webhook_var),
        ("Carrier Zielsystem", carrier_target_var),
        ("Carrier Sprünge geplant", carrier_planned_jumps_var),
        ("Carrier Entfernung gesamt (ly)", carrier_planned_distance_var),
        ("Carrier Bild-URL", carrier_image_var),
    ]

    pref_controls.clear()
    ship_image_mapping_vars.clear()
    carrier_image_mapping_vars.clear()
    ship_image_mapping_tree = None
    carrier_image_mapping_tree = None
    for row_index, row in enumerate(rows, start=1):
        label = row[0]
        variable = row[1]
        editable = bool(row[2]) if len(row) > 2 else True
        make_label(frame, text=label).grid(row=row_index, column=0, sticky="w", padx=4, pady=2)
        if editable:
            entry = make_entry(frame, textvariable=variable, width=60)
            entry.grid(row=row_index, column=1, sticky="ew", padx=4, pady=2)
            pref_controls.append(entry)
        else:
            make_label(frame, textvariable=variable).grid(
                row=row_index, column=1, sticky="w", padx=4, pady=2
            )

    next_row = len(rows) + 1
    ship_table = create_image_table(
        frame,
        next_row,
        "Gespeicherte Schiff-Bilder",
        get_ship_image_urls(),
    )
    ship_image_mapping_tree = ship_table["tree"]
    carrier_table = create_image_table(
        frame,
        ship_table["next_row"],
        "Gespeicherte Carrier-Bilder",
        get_carrier_image_urls(),
    )
    carrier_image_mapping_tree = carrier_table["tree"]
    update_ui_enabled()

    return frame


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """Persist changed preferences from EDMC's settings dialog."""
    del cmdr, is_beta

    apply_pref_vars()
    save_state()
    update_ui_enabled()
    active_ship = current_ship_name or str(state["ship"].get("active_ship_name") or "")
    if active_ship and ship_image_var is not None:
        set_status(f"Einstellungen gespeichert. Schiffbild für {active_ship} gemerkt.")
    else:
        set_status("Einstellungen gespeichert.")


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: Dict[str, Any],
    state_data: Dict[str, Any],
) -> None:
    """EDMC journal callback."""
    del is_beta, station

    update_session_context(cmdr, system, entry, state_data)
    update_active_ship(entry, state_data)
    update_active_carrier(entry, state_data)
    if not plugin_enabled():
        return

    event = entry.get("event")
    if event == "NavRoute":
        handle_nav_route(entry)
    elif event == "FSDJump":
        handle_jump("ship", entry, system)
    elif event == "CarrierJump":
        handle_jump("carrier", entry, system)


def load_state() -> Dict[str, Any]:
    """Load persisted route progress and merge it with the current schema."""
    loaded = copy.deepcopy(DEFAULT_STATE)

    if not state_path or not os.path.exists(state_path):
        return loaded

    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        set_status(f"State konnte nicht geladen werden: {exc}")
        return loaded

    if not isinstance(raw, dict):
        return loaded

    loaded["autopost"] = bool(raw.get("autopost", loaded.get("autopost", False)))
    loaded["plugin_enabled"] = bool(
        raw.get("plugin_enabled", loaded.get("plugin_enabled", True))
    )

    for kind in TRACKER_KINDS:
        raw_tracker = raw.get(kind, {})
        if isinstance(raw_tracker, dict):
            loaded[kind].update(raw_tracker)
            loaded[kind]["last_pos"] = normalize_pos(loaded[kind].get("last_pos"))
            loaded[kind]["messages"] = normalize_messages(
                loaded[kind].get("messages"),
                loaded[kind].get("webhook_url"),
                loaded[kind].get("message_id"),
            )
            loaded[kind]["poster_name"] = str(loaded[kind].get("poster_name") or "")
            loaded[kind]["jumps_done"] = int_or_default(loaded[kind].get("jumps_done"), 0)
            loaded[kind]["distance_done"] = float_or_default(
                loaded[kind].get("distance_done"), 0.0
            )
            loaded[kind]["last_jump_distance"] = float_or_default(
                loaded[kind].get("last_jump_distance"), 0.0
            )
            loaded[kind]["longest_jump_distance"] = float_or_default(
                loaded[kind].get("longest_jump_distance"), 0.0
            )
            loaded[kind]["shortest_jump_distance"] = float_or_default(
                loaded[kind].get("shortest_jump_distance"), 0.0
            )
            loaded[kind]["planned_jumps"] = int_or_default(
                loaded[kind].get("planned_jumps"), 0
            )
            loaded[kind]["planned_distance"] = float_or_default(
                loaded[kind].get("planned_distance"), 0.0
            )
            loaded[kind]["route_systems"] = normalize_route_systems(
                loaded[kind].get("route_systems")
            )
            loaded[kind]["start_time"] = str(loaded[kind].get("start_time") or "")
            loaded[kind]["end_time"] = str(loaded[kind].get("end_time") or "")
            loaded[kind]["route_completed"] = bool(loaded[kind].get("route_completed"))

    if not isinstance(loaded["ship"].get("image_urls_by_ship"), dict):
        loaded["ship"]["image_urls_by_ship"] = {}
    loaded["ship"]["active_ship_name"] = str(loaded["ship"].get("active_ship_name") or "")
    if not isinstance(loaded["carrier"].get("image_urls_by_carrier"), dict):
        loaded["carrier"]["image_urls_by_carrier"] = {}
    loaded["carrier"]["active_carrier_name"] = str(
        loaded["carrier"].get("active_carrier_name") or ""
    )

    return loaded


def save_state() -> None:
    """Write current route progress to the plugin directory."""
    if not state_path:
        return

    try:
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
    except Exception as exc:
        set_status(f"State konnte nicht gespeichert werden: {exc}")


def check_for_updates(silent: bool = False) -> None:
    """Check a remote update manifest and install a newer plugin file if available."""
    if not UPDATE_MANIFEST_URL:
        if not silent:
            set_status("Keine Update-URL konfiguriert.")
        return
    if requests is None:
        if not silent:
            set_status("Update nicht möglich: requests-Modul fehlt.")
        return

    try:
        manifest = fetch_update_manifest()
        latest_version = str(manifest.get("version") or "").strip()
        if not latest_version:
            raise ValueError("Manifest enthält keine Version.")
        if not is_newer_version(latest_version, PLUGIN_VERSION):
            if not silent:
                set_status(f"{PLUGIN_NAME} ist aktuell ({PLUGIN_VERSION}).")
            return

        files = update_files_from_manifest(manifest)
        if not files:
            raise ValueError("Manifest enthält keine aktualisierbaren Dateien.")

        install_update_files(files)
        set_status(
            f"Update {latest_version} installiert. Bitte EDMC neu starten."
        )
    except Exception as exc:
        if not silent:
            set_status(f"Update fehlgeschlagen: {exc}")


def fetch_update_manifest() -> Dict[str, Any]:
    response = requests.get(UPDATE_MANIFEST_URL, timeout=15)  # type: ignore[union-attr]
    response.raise_for_status()
    manifest = response.json()
    if not isinstance(manifest, dict):
        raise ValueError("Manifest ist kein JSON-Objekt.")
    return manifest


def update_files_from_manifest(manifest: Dict[str, Any]) -> Dict[str, str]:
    files = manifest.get("files")
    if isinstance(files, dict):
        return {
            str(path): str(url)
            for path, url in files.items()
            if str(path) in UPDATE_FILE_ALLOWLIST and str(url).startswith(("http://", "https://"))
        }

    download_url = str(manifest.get("download_url") or "").strip()
    if download_url.startswith(("http://", "https://")):
        return {"load.py": download_url}

    return {}


def install_update_files(files: Dict[str, str]) -> None:
    if not plugin_dir_path:
        raise ValueError("Plugin-Verzeichnis ist nicht bekannt.")

    for relative_path, download_url in files.items():
        if relative_path not in UPDATE_FILE_ALLOWLIST:
            continue

        target_path = os.path.abspath(os.path.join(plugin_dir_path, relative_path))
        plugin_root = os.path.abspath(plugin_dir_path)
        if os.path.commonpath([plugin_root, target_path]) != plugin_root:
            raise ValueError(f"Ungültiger Update-Pfad: {relative_path}")

        response = requests.get(download_url, timeout=30)  # type: ignore[union-attr]
        response.raise_for_status()
        content = response.text
        if relative_path == "load.py" and PLUGIN_NAME not in content:
            raise ValueError("Update-Datei sieht nicht wie DiscordRouteTracker aus.")

        backup_path = f"{target_path}.bak"
        temp_path = f"{target_path}.update"
        if os.path.exists(target_path):
            with open(target_path, "rb") as source, open(backup_path, "wb") as backup:
                backup.write(source.read())
        with open(temp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_path, target_path)


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = version_parts(candidate)
    current_parts = version_parts(current)
    max_length = max(len(candidate_parts), len(current_parts))
    candidate_parts.extend([0] * (max_length - len(candidate_parts)))
    current_parts.extend([0] * (max_length - len(current_parts)))
    return candidate_parts > current_parts


def version_parts(value: str) -> List[int]:
    parts = [int(part) for part in re.findall(r"\d+", value)]
    return parts if parts else [0]


def reset_tracker(kind: str) -> None:
    """Reset one tracker while keeping user configuration values."""
    if kind not in TRACKER_KINDS:
        return

    apply_pref_vars()
    tracker = state[kind]
    keep_poster_name = tracker.get("poster_name", "")
    keep_webhook = tracker.get("webhook_url", "")
    keep_image = tracker.get("image_url", "")
    keep_active_ship_name = tracker.get("active_ship_name", "")
    keep_image_urls_by_ship = tracker.get("image_urls_by_ship", {})
    keep_active_carrier_name = tracker.get("active_carrier_name", "")
    keep_image_urls_by_carrier = tracker.get("image_urls_by_carrier", {})

    state[kind] = copy.deepcopy(DEFAULT_TRACKER_STATE)
    state[kind]["poster_name"] = keep_poster_name
    state[kind]["webhook_url"] = keep_webhook
    state[kind]["image_url"] = keep_image
    if kind == "ship":
        state[kind]["active_ship_name"] = keep_active_ship_name
        state[kind]["image_urls_by_ship"] = keep_image_urls_by_ship
    elif kind == "carrier":
        state[kind]["active_carrier_name"] = keep_active_carrier_name
        state[kind]["image_urls_by_carrier"] = keep_image_urls_by_carrier

    refresh_pref_vars(kind)
    save_state()
    set_status(f"{DISPLAY_NAMES[kind]} zurückgesetzt.")


def send_initial_embed(kind: str) -> None:
    """Create or resend the initial Discord embed and store its message ID."""
    if kind not in TRACKER_KINDS:
        return
    if not plugin_enabled():
        set_status("Plugin ist deaktiviert.")
        return

    if not game_running:
        set_status("Warte auf Spiel.")
        return
    if not current_system_name:
        set_status("Warte auf aktuelles System.")
        return

    apply_pref_vars()
    tracker = state[kind]
    if current_system_name:
        tracker["start_system"] = current_system_name
        tracker["current_system"] = current_system_name
        if not normalize_route_systems(tracker.get("route_systems")):
            tracker["route_systems"] = [current_system_name]
    if current_system_pos is not None:
        tracker["last_pos"] = current_system_pos

    webhook_urls = webhook_urls_for_tracker(kind)
    if not webhook_urls:
        set_status(f"{DISPLAY_NAMES[kind]}: Webhook-URL fehlt.")
        return
    if requests is None:
        set_status("Discord-Request nicht möglich: requests-Modul fehlt.")
        return

    payload = build_webhook_payload(kind, include_username=True)
    sent_messages: List[Dict[str, str]] = []
    errors: List[str] = []

    for webhook_url in webhook_urls:
        response = None
        try:
            response = requests.post(webhook_with_wait(webhook_url), json=payload, timeout=15)
            response.raise_for_status()
            response_data = response.json()
        except Exception as exc:
            errors.append(f"{short_webhook_label(webhook_url)}: {exc}{discord_error_detail(response)}")
            continue

        message_id = response_data.get("id") if isinstance(response_data, dict) else None
        if not message_id:
            errors.append(f"{short_webhook_label(webhook_url)}: Antwort ohne Message ID")
            continue
        sent_messages.append({"webhook_url": webhook_url, "message_id": str(message_id)})

    if not sent_messages:
        set_status(f"{DISPLAY_NAMES[kind]}: Discord POST fehlgeschlagen: {'; '.join(errors)}")
        return

    tracker["messages"] = sent_messages
    tracker["message_id"] = sent_messages[0]["message_id"]
    save_state()
    if errors:
        set_status(
            f"{DISPLAY_NAMES[kind]}-Embed an {len(sent_messages)} Webhook(s) gesendet; Fehler: {'; '.join(errors)}"
        )
    else:
        set_status(f"{DISPLAY_NAMES[kind]}-Embed an {len(sent_messages)} Webhook(s) gesendet.")


def update_discord_message(kind: str) -> None:
    """Patch the already-created Discord webhook message."""
    if kind not in TRACKER_KINDS:
        return

    tracker = state[kind]
    messages = messages_for_tracker(kind)
    if not messages:
        return
    if requests is None:
        set_status("Discord-Update nicht möglich: requests-Modul fehlt.")
        return

    payload = build_webhook_payload(kind, include_username=False)
    updated_messages: List[Dict[str, str]] = []
    errors: List[str] = []

    for message in messages:
        webhook_url = str(message.get("webhook_url") or "").strip()
        message_id = str(message.get("message_id") or "").strip()
        if not webhook_url or not message_id:
            continue
        response = None
        try:
            response = requests.patch(
                webhook_message_url(webhook_url, message_id),
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
            updated_messages.append({"webhook_url": webhook_url, "message_id": message_id})
        except Exception as exc:
            errors.append(f"{short_webhook_label(webhook_url)}: {exc}{discord_error_detail(response)}")

    if updated_messages:
        tracker["messages"] = updated_messages
        tracker["message_id"] = updated_messages[0]["message_id"]
        save_state()

    if errors and not updated_messages:
        set_status(f"{DISPLAY_NAMES[kind]}: Discord PATCH fehlgeschlagen: {'; '.join(errors)}")
    elif errors:
        set_status(
            f"{DISPLAY_NAMES[kind]}-Embed teilweise aktualisiert; Fehler: {'; '.join(errors)}"
        )
    else:
        set_status(f"{DISPLAY_NAMES[kind]}-Embed aktualisiert.")


def build_embed(kind: str) -> Dict[str, Any]:
    """Build a Discord embed payload for one tracker."""
    tracker = state[kind]
    image_url = image_url_for_tracker(kind)
    planned_jumps = int_or_default(tracker.get("planned_jumps"), 0)
    planned_distance = float_or_default(tracker.get("planned_distance"), 0.0)
    distance_done = float_or_default(tracker.get("distance_done"), 0.0)
    jumps_done = int_or_default(tracker.get("jumps_done"), 0)
    jumps_remaining = max(planned_jumps - jumps_done, 0) if planned_jumps > 0 else 0
    distance_remaining = max(planned_distance - distance_done, 0.0) if planned_distance > 0 else 0.0
    average_jump_distance = distance_done / jumps_done if jumps_done > 0 else 0.0

    embed: Dict[str, Any] = {
        "title": build_embed_title(kind),
        "color": 3447003 if kind == "ship" else 15844367,
        "fields": [
            {
                "name": "Startsystem",
                "value": system_field_value(tracker.get("start_system")),
                "inline": False,
            },
            {
                "name": "Aktuelles System",
                "value": system_field_value(tracker.get("current_system")),
                "inline": False,
            },
            {
                "name": "Zielsystem",
                "value": system_field_value(tracker.get("target_system")),
                "inline": False,
            },
            {
                "name": "Startzeit",
                "value": timestamp_field_value(tracker.get("start_time")),
                "inline": True,
            },
            {
                "name": "Endzeit",
                "value": timestamp_field_value(tracker.get("end_time")),
                "inline": True,
            },
            *route_embed_fields(kind),
            {
                "name": "Sprünge geplant",
                "value": str(planned_jumps) if planned_jumps > 0 else "-",
                "inline": True,
            },
            {
                "name": "Sprünge erledigt",
                "value": str(jumps_done),
                "inline": True,
            },
            {
                "name": "Sprünge verbleibend",
                "value": str(jumps_remaining) if planned_jumps > 0 else "-",
                "inline": True,
            },
            {
                "name": "Letzter Sprung",
                "value": f"{float_or_default(tracker.get('last_jump_distance'), 0.0):.2f} ly",
                "inline": True,
            },
            {
                "name": "Weitester Sprung",
                "value": f"{float_or_default(tracker.get('longest_jump_distance'), 0.0):.2f} ly",
                "inline": True,
            },
            {
                "name": "Kürzester Sprung",
                "value": f"{float_or_default(tracker.get('shortest_jump_distance'), 0.0):.2f} ly",
                "inline": True,
            },
            {
                "name": "Durchschnitt pro Sprung",
                "value": f"{average_jump_distance:.2f} ly" if jumps_done > 0 else "-",
                "inline": False,
            },
            {
                "name": "Entfernung gesamt",
                "value": f"{planned_distance:.2f} ly" if planned_distance > 0 else "-",
                "inline": True,
            },
            {
                "name": "Entfernung zurückgelegt",
                "value": f"{distance_done:.2f} ly",
                "inline": True,
            },
            {
                "name": "Entfernung verbleibend",
                "value": f"{distance_remaining:.2f} ly" if planned_distance > 0 else "-",
                "inline": True,
            },
        ],
    }

    if is_http_url(image_url):
        embed["image"] = {"url": image_url}

    if tracker.get("route_completed"):
        embed["fields"].append(
            {
                "name": "Status",
                "value": "**Route abgeschlossen und Ziel erreicht**",
                "inline": False,
            }
        )

    return embed


def build_webhook_payload(kind: str, include_username: bool) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"embeds": [build_embed(kind)]}
    poster_name = str(state[kind].get("poster_name") or "").strip()
    if include_username and poster_name:
        payload["username"] = poster_name
    return payload


def webhook_urls_for_tracker(kind: str) -> List[str]:
    return split_webhook_urls(str(state[kind].get("webhook_url") or ""))


def split_webhook_urls(value: str) -> List[str]:
    urls: List[str] = []
    seen = set()
    for part in value.split(";"):
        webhook_url = part.strip()
        if not webhook_url or webhook_url in seen:
            continue
        urls.append(webhook_url)
        seen.add(webhook_url)
    return urls


def messages_for_tracker(kind: str) -> List[Dict[str, str]]:
    tracker = state[kind]
    messages = normalize_messages(
        tracker.get("messages"),
        tracker.get("webhook_url"),
        tracker.get("message_id"),
    )
    tracker["messages"] = messages
    return messages


def normalize_messages(
    raw_messages: Any,
    webhook_value: Any,
    legacy_message_id: Any,
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen = set()

    if isinstance(raw_messages, list):
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            webhook_url = str(item.get("webhook_url") or "").strip()
            message_id = str(item.get("message_id") or "").strip()
            key = (webhook_url, message_id)
            if webhook_url and message_id and key not in seen:
                normalized.append({"webhook_url": webhook_url, "message_id": message_id})
                seen.add(key)

    if not normalized:
        webhook_urls = split_webhook_urls(str(webhook_value or ""))
        message_id = str(legacy_message_id or "").strip()
        if len(webhook_urls) == 1 and message_id:
            normalized.append({"webhook_url": webhook_urls[0], "message_id": message_id})

    current_urls = set(split_webhook_urls(str(webhook_value or "")))
    if current_urls:
        normalized = [
            message for message in normalized if message["webhook_url"] in current_urls
        ]

    return normalized


def short_webhook_label(webhook_url: str) -> str:
    parts = urlsplit(webhook_url)
    path_tail = parts.path.rstrip("/").split("/")[-1] if parts.path else ""
    if path_tail:
        return f"...{path_tail[-8:]}"
    return parts.netloc or "Webhook"


def image_url_for_tracker(kind: str) -> str:
    if kind == "ship":
        ship_name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
        image_url = get_ship_image_urls().get(ship_name, "")
        state["ship"]["image_url"] = image_url
        return str(image_url or "").strip()

    carrier_name = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "")
    image_url = get_carrier_image_urls().get(carrier_name, "")
    state["carrier"]["image_url"] = image_url
    return str(image_url or "").strip()


def handle_jump(kind: str, entry: Dict[str, Any], system: str) -> None:
    """Apply one FSDJump or CarrierJump journal event to one tracker."""
    if kind not in TRACKER_KINDS:
        return

    tracker = state[kind]
    system_name = entry.get("StarSystem") or system or ""
    current_pos = normalize_pos(entry.get("StarPos"))
    previous_pos = normalize_pos(tracker.get("last_pos"))
    jump_time = journal_timestamp(entry)

    if not tracker.get("start_system"):
        tracker["start_system"] = system_name
    if not tracker.get("start_time"):
        tracker["start_time"] = jump_time

    tracker["current_system"] = system_name
    append_route_system(kind, system_name)

    if current_pos is None:
        jump_distance = float_or_default(entry.get("JumpDist"), 0.0)
        tracker["last_jump_distance"] = jump_distance
        tracker["distance_done"] = float_or_default(tracker.get("distance_done"), 0.0) + jump_distance
        update_jump_extremes(tracker, jump_distance)
        tracker["last_pos"] = None
        set_status(f"{DISPLAY_NAMES[kind]}: Sprung ohne StarPos gespeichert.")
    else:
        if previous_pos is None:
            jump_distance = float_or_default(entry.get("JumpDist"), 0.0)
        else:
            jump_distance = distance_ly(previous_pos, current_pos)

        tracker["last_jump_distance"] = jump_distance
        tracker["distance_done"] = float_or_default(tracker.get("distance_done"), 0.0) + jump_distance
        update_jump_extremes(tracker, jump_distance)
        tracker["last_pos"] = current_pos

    tracker["jumps_done"] = int_or_default(tracker.get("jumps_done"), 0) + 1
    update_route_completion(kind, jump_time)
    save_state()

    if messages_for_tracker(kind):
        update_discord_message(kind)
        if tracker.get("route_completed"):
            tracker["message_id"] = ""
            tracker["messages"] = []
            save_state()
            set_status(f"{DISPLAY_NAMES[kind]}-Route abgeschlossen. Embed-ID vergessen.")
    else:
        set_status(f"{DISPLAY_NAMES[kind]}-Fortschritt gespeichert.")


def distance_ly(a: List[float], b: List[float]) -> float:
    """Return Euclidean distance in light years between two StarPos values."""
    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


def update_jump_extremes(tracker: Dict[str, Any], jump_distance: float) -> None:
    """Update longest and shortest jump stats, ignoring unknown/zero first distances."""
    if jump_distance <= 0:
        return

    longest = float_or_default(tracker.get("longest_jump_distance"), 0.0)
    shortest = float_or_default(tracker.get("shortest_jump_distance"), 0.0)

    if longest <= 0 or jump_distance > longest:
        tracker["longest_jump_distance"] = jump_distance
    if shortest <= 0 or jump_distance < shortest:
        tracker["shortest_jump_distance"] = jump_distance


def update_session_context(
    cmdr: str,
    system: str,
    entry: Dict[str, Any],
    state_data: Dict[str, Any],
) -> None:
    """Remember current EDMC session data and unlock controls once the game is visible."""
    global current_cmdr_name, current_system_name, current_system_pos, game_running

    if state_data is None:
        state_data = {}

    cmdr_name = str(cmdr or state_data.get("Commander") or entry.get("Commander") or "").strip()
    system_name = str(
        entry.get("StarSystem")
        or system
        or state_data.get("System")
        or state_data.get("system")
        or ""
    ).strip()
    system_pos = normalize_pos(entry.get("StarPos") or state_data.get("StarPos"))

    if cmdr_name:
        current_cmdr_name = cmdr_name
    if system_name:
        current_system_name = system_name
        state["ship"]["current_system"] = system_name
        state["carrier"]["current_system"] = system_name
    if system_pos is not None:
        current_system_pos = system_pos

    if not game_running and (current_cmdr_name or current_system_name):
        game_running = True
        update_ui_enabled()
        set_status("Spiel erkannt.")


def handle_nav_route(entry: Dict[str, Any]) -> None:
    """Use the in-game plotted route for planned ship jumps when allowed."""
    planned_jumps = planned_jumps_from_nav_route(entry)
    planned_distance = planned_distance_from_nav_route(entry)
    target_system = target_system_from_nav_route(entry)
    route_systems = route_systems_from_nav_route(entry)
    if planned_jumps <= 0 and planned_distance <= 0 and not target_system:
        return

    tracker = state["ship"]
    if not messages_for_tracker("ship"):
        clear_route_settings_for_nav_route("ship")

    has_active_plan = (
        int_or_default(tracker.get("planned_jumps"), 0) > 0
        or float_or_default(tracker.get("planned_distance"), 0.0) > 0
        or bool(str(tracker.get("target_system") or "").strip())
    )
    if has_active_plan and not tracker.get("route_completed"):
        return

    if tracker.get("route_completed"):
        reset_progress_for_new_route("ship")

    if target_system:
        tracker["target_system"] = target_system
    if planned_jumps > 0:
        tracker["planned_jumps"] = planned_jumps
    if planned_distance > 0:
        tracker["planned_distance"] = planned_distance
    if route_systems:
        tracker["route_systems"] = route_systems
    tracker["route_completed"] = False
    refresh_pref_vars("ship")
    if ship_planned_jumps_var is not None:
        ship_planned_jumps_var.set(planned_jumps_text("ship"))
    if ship_planned_distance_var is not None:
        ship_planned_distance_var.set(planned_distance_text("ship"))

    save_state()
    if autopost_enabled() and not messages_for_tracker("ship"):
        send_initial_embed("ship")
    elif messages_for_tracker("ship"):
        update_discord_message("ship")
    else:
        set_status("Nav-Route erkannt.")


def reset_progress_for_new_route(kind: str) -> None:
    tracker = state[kind]
    tracker["start_system"] = current_system_name
    tracker["current_system"] = current_system_name
    tracker["jumps_done"] = 0
    tracker["distance_done"] = 0.0
    tracker["last_jump_distance"] = 0.0
    tracker["longest_jump_distance"] = 0.0
    tracker["shortest_jump_distance"] = 0.0
    tracker["last_pos"] = current_system_pos
    tracker["route_systems"] = [current_system_name] if current_system_name else []
    tracker["start_time"] = ""
    tracker["end_time"] = ""


def clear_route_settings_for_nav_route(kind: str) -> None:
    """Clear stale route settings before accepting a new plotted route."""
    tracker = state[kind]
    tracker["target_system"] = ""
    tracker["planned_jumps"] = 0
    tracker["planned_distance"] = 0.0
    tracker["route_completed"] = False
    reset_progress_for_new_route(kind)


def planned_jumps_from_nav_route(entry: Dict[str, Any]) -> int:
    route = entry.get("Route")
    if not isinstance(route, list) or not route:
        return 0

    route_systems = [
        str(item.get("StarSystem") or "").strip()
        for item in route
        if isinstance(item, dict)
    ]
    route_systems = [name for name in route_systems if name]
    if not route_systems:
        return len(route)

    if current_system_name and same_system(route_systems[0], current_system_name):
        return max(len(route_systems) - 1, 0)

    return len(route_systems)


def target_system_from_nav_route(entry: Dict[str, Any]) -> str:
    route = entry.get("Route")
    if not isinstance(route, list) or not route:
        return ""

    for item in reversed(route):
        if isinstance(item, dict):
            system_name = str(item.get("StarSystem") or "").strip()
            if system_name:
                return system_name

    return ""


def route_systems_from_nav_route(entry: Dict[str, Any]) -> List[str]:
    route = entry.get("Route")
    if not isinstance(route, list) or not route:
        return []

    systems = normalize_route_systems(
        [
            item.get("StarSystem")
            for item in route
            if isinstance(item, dict)
        ]
    )
    if current_system_name and (
        not systems or not same_system(systems[0], current_system_name)
    ):
        systems.insert(0, current_system_name)
    return systems


def planned_distance_from_nav_route(entry: Dict[str, Any]) -> float:
    route = entry.get("Route")
    if not isinstance(route, list) or not route:
        return 0.0

    positions = [
        normalize_pos(item.get("StarPos"))
        for item in route
        if isinstance(item, dict)
    ]
    positions = [pos for pos in positions if pos is not None]

    if len(positions) < 2:
        return 0.0

    total = 0.0
    for index in range(1, len(positions)):
        total += distance_ly(positions[index - 1], positions[index])
    return total


def apply_manual_planned_jumps(kind: str, value: str) -> None:
    planned_jumps = int_or_default(str(value or "").strip(), 0)
    tracker = state[kind]
    if planned_jumps > 0 and tracker.get("route_completed"):
        reset_progress_for_new_route(kind)
    tracker["planned_jumps"] = max(planned_jumps, 0)
    if tracker["planned_jumps"] > 0:
        tracker["route_completed"] = False


def apply_manual_planned_distance(kind: str, value: str) -> None:
    planned_distance = float_or_default(str(value or "").strip().replace(",", "."), 0.0)
    tracker = state[kind]
    if planned_distance > 0 and tracker.get("route_completed"):
        reset_progress_for_new_route(kind)
    tracker["planned_distance"] = max(planned_distance, 0.0)
    if tracker["planned_distance"] > 0:
        tracker["route_completed"] = False
    elif not is_target_reached(kind):
        tracker["route_completed"] = False


def update_route_completion(kind: str, completed_time: str = "") -> None:
    if is_target_reached(kind):
        tracker = state[kind]
        tracker["route_completed"] = True
        if not tracker.get("end_time"):
            tracker["end_time"] = completed_time or current_utc_timestamp()


def is_target_reached(kind: str) -> bool:
    tracker = state[kind]
    target = str(tracker.get("target_system") or "").strip()
    current = str(tracker.get("current_system") or "").strip()
    return bool(target and current and same_system(target, current))


def same_system(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def planned_jumps_text(kind: str) -> str:
    planned_jumps = int_or_default(state[kind].get("planned_jumps"), 0)
    return str(planned_jumps) if planned_jumps > 0 else ""


def planned_distance_text(kind: str) -> str:
    planned_distance = float_or_default(state[kind].get("planned_distance"), 0.0)
    return f"{planned_distance:.2f}" if planned_distance > 0 else ""


def update_ui_enabled() -> None:
    """Enable plugin controls only after EDMC has seen the running game."""
    if main_app_frame is not None:
        try:
            if plugin_enabled():
                main_app_frame.grid()
            else:
                main_app_frame.grid_remove()
        except Exception:
            pass

    desired_state = "normal" if game_running else "disabled"
    for widget in main_controls + pref_controls:
        set_widget_state(widget, desired_state)
    ship_send_state = "disabled" if autopost_enabled() or not game_running else "normal"
    for widget in ship_send_controls:
        set_widget_state(widget, ship_send_state)
    carrier_send_state = "normal" if game_running else "disabled"
    for widget in send_controls:
        if widget in ship_send_controls:
            continue
        set_widget_state(widget, carrier_send_state)


def autopost_enabled() -> bool:
    return bool(state.get("autopost", False))


def plugin_enabled() -> bool:
    return bool(state.get("plugin_enabled", True))


def autopost_changed() -> None:
    if autopost_var is not None:
        state["autopost"] = bool(autopost_var.get())
    save_state()
    update_ui_enabled()
    if autopost_enabled():
        set_status("Autopost aktiv. Route plotten erstellt ein Schiff-Embed.")
    else:
        set_status("Autopost aus. Embeds werden manuell erstellt.")


def set_widget_state(widget: Any, desired_state: str) -> None:
    if hasattr(widget, "_drt_enabled"):
        widget._drt_enabled = desired_state != "disabled"
        apply_skin(widget, widget.master, "button")
        try:
            widget.configure(cursor="hand2" if widget._drt_enabled else "")
        except Exception:
            pass
        return

    try:
        widget.configure(state=desired_state)
    except Exception:
        pass


def build_embed_title(kind: str) -> str:
    commander = current_cmdr_name or "Kommandant"
    if kind == "ship":
        vehicle = current_ship_name or str(state["ship"].get("active_ship_name") or "").strip()
        if not vehicle:
            vehicle = "Schiff"
    else:
        vehicle = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "").strip()
        if not vehicle:
            vehicle = "Carrier"
    return f"{commander} - {vehicle}"


def active_vehicle_text(kind: str) -> str:
    if kind == "ship":
        name = current_ship_name or str(state["ship"].get("active_ship_name") or "").strip()
        return name if name else "Noch nicht erkannt"

    name = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "").strip()
    return name if name else "Noch nicht erkannt"


def refresh_pref_vars(kind: str) -> None:
    if kind == "ship":
        if ship_poster_name_var is not None:
            ship_poster_name_var.set(str(state["ship"].get("poster_name") or ""))
        if ship_webhook_var is not None:
            ship_webhook_var.set(str(state["ship"].get("webhook_url") or ""))
        if ship_target_var is not None:
            ship_target_var.set(str(state["ship"].get("target_system") or ""))
        if ship_image_var is not None:
            ship_image_var.set(get_current_ship_image_url())
        if ship_planned_jumps_var is not None:
            ship_planned_jumps_var.set(planned_jumps_text("ship"))
        if ship_planned_distance_var is not None:
            ship_planned_distance_var.set(planned_distance_text("ship"))
        if active_ship_label_var is not None:
            active_ship_label_var.set(active_vehicle_text("ship"))
    elif kind == "carrier":
        if carrier_poster_name_var is not None:
            carrier_poster_name_var.set(str(state["carrier"].get("poster_name") or ""))
        if carrier_webhook_var is not None:
            carrier_webhook_var.set(str(state["carrier"].get("webhook_url") or ""))
        if carrier_target_var is not None:
            carrier_target_var.set(str(state["carrier"].get("target_system") or ""))
        if carrier_image_var is not None:
            carrier_image_var.set(get_current_carrier_image_url())
        if carrier_planned_jumps_var is not None:
            carrier_planned_jumps_var.set(planned_jumps_text("carrier"))
        if carrier_planned_distance_var is not None:
            carrier_planned_distance_var.set(planned_distance_text("carrier"))
        if active_carrier_label_var is not None:
            active_carrier_label_var.set(active_vehicle_text("carrier"))


def open_settings_dialog(parent: Any) -> None:
    if tk is None:
        return
    if ttk is None:
        set_status("Einstellungsdialog benötigt tkinter.ttk.")
        return

    dialog = tk.Toplevel(parent)
    dialog.title("DiscordRouteTracker Einstellungen")
    dialog.columnconfigure(0, weight=1)
    apply_skin(dialog, parent, "frame")
    try:
        dialog.transient(parent)
        dialog.grab_set()
    except Exception:
        pass

    content = make_frame(dialog)
    content.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
    content.columnconfigure(1, weight=1)

    dialog_vars = {
        "plugin_enabled": tk.BooleanVar(value=plugin_enabled()),
        "ship_poster_name": tk.StringVar(value=str(state["ship"].get("poster_name") or "")),
        "ship_webhook": tk.StringVar(value=str(state["ship"].get("webhook_url") or "")),
        "ship_target": tk.StringVar(value=str(state["ship"].get("target_system") or "")),
        "ship_image": tk.StringVar(value=get_current_ship_image_url()),
        "ship_planned_jumps": tk.StringVar(value=planned_jumps_text("ship")),
        "ship_planned_distance": tk.StringVar(value=planned_distance_text("ship")),
        "carrier_poster_name": tk.StringVar(value=str(state["carrier"].get("poster_name") or "")),
        "carrier_webhook": tk.StringVar(value=str(state["carrier"].get("webhook_url") or "")),
        "carrier_target": tk.StringVar(value=str(state["carrier"].get("target_system") or "")),
        "carrier_image": tk.StringVar(value=get_current_carrier_image_url()),
        "carrier_planned_jumps": tk.StringVar(value=planned_jumps_text("carrier")),
        "carrier_planned_distance": tk.StringVar(value=planned_distance_text("carrier")),
    }

    rows = [
        ("Plugin aktiv", dialog_vars["plugin_enabled"], True, "check"),
        ("Aktuelles Schiff", tk.StringVar(value=active_vehicle_text("ship")), False),
        ("Schiff Discord-Name", dialog_vars["ship_poster_name"], True),
        ("Schiff Webhook", dialog_vars["ship_webhook"], True),
        ("Schiff Zielsystem", dialog_vars["ship_target"], True),
        ("Schiff Sprünge geplant", dialog_vars["ship_planned_jumps"], True),
        ("Schiff Entfernung gesamt (ly)", dialog_vars["ship_planned_distance"], True),
        ("Schiff Bild-URL", dialog_vars["ship_image"], True),
        ("Aktueller Carrier", tk.StringVar(value=active_vehicle_text("carrier")), False),
        ("Carrier Discord-Name", dialog_vars["carrier_poster_name"], True),
        ("Carrier Webhook", dialog_vars["carrier_webhook"], True),
        ("Carrier Zielsystem", dialog_vars["carrier_target"], True),
        ("Carrier Sprünge geplant", dialog_vars["carrier_planned_jumps"], True),
        ("Carrier Entfernung gesamt (ly)", dialog_vars["carrier_planned_distance"], True),
        ("Carrier Bild-URL", dialog_vars["carrier_image"], True),
    ]

    for row_index, row in enumerate(rows):
        label = row[0]
        variable = row[1]
        editable = bool(row[2])
        control_type = str(row[3]) if len(row) > 3 else "entry"
        if control_type == "check":
            make_checkbutton(content, text=label, variable=variable).grid(
                row=row_index, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 8)
            )
            continue

        make_label(content, text=label).grid(row=row_index, column=0, sticky="w", padx=4, pady=2)
        if editable:
            make_entry(content, textvariable=variable, width=70).grid(
                row=row_index, column=1, sticky="ew", padx=4, pady=2
            )
        else:
            make_label(content, textvariable=variable).grid(
                row=row_index, column=1, sticky="w", padx=4, pady=2
            )

    next_row = len(rows)
    ship_table = create_image_table(
        content,
        next_row,
        "Gespeicherte Schiff-Bilder",
        get_ship_image_urls(),
    )
    carrier_table = create_image_table(
        content,
        ship_table["next_row"],
        "Gespeicherte Carrier-Bilder",
        get_carrier_image_urls(),
    )

    buttons = make_frame(content)
    buttons.grid(row=carrier_table["next_row"], column=0, columnspan=2, sticky="e", pady=(10, 0))

    def save_dialog() -> None:
        state["plugin_enabled"] = bool(dialog_vars["plugin_enabled"].get())
        state["ship"]["poster_name"] = dialog_vars["ship_poster_name"].get().strip()
        state["ship"]["webhook_url"] = dialog_vars["ship_webhook"].get().strip()
        state["ship"]["target_system"] = dialog_vars["ship_target"].get().strip()
        state["ship"]["image_url"] = dialog_vars["ship_image"].get().strip()
        state["ship"]["image_urls_by_ship"] = image_mapping_from_tree(ship_table["tree"])
        save_dialog_active_image("ship", state["ship"]["image_url"])
        apply_manual_planned_jumps("ship", dialog_vars["ship_planned_jumps"].get())
        apply_manual_planned_distance("ship", dialog_vars["ship_planned_distance"].get())

        state["carrier"]["poster_name"] = dialog_vars["carrier_poster_name"].get().strip()
        state["carrier"]["webhook_url"] = dialog_vars["carrier_webhook"].get().strip()
        state["carrier"]["target_system"] = dialog_vars["carrier_target"].get().strip()
        state["carrier"]["image_url"] = dialog_vars["carrier_image"].get().strip()
        state["carrier"]["image_urls_by_carrier"] = image_mapping_from_tree(carrier_table["tree"])
        save_dialog_active_image("carrier", state["carrier"]["image_url"])
        apply_manual_planned_jumps("carrier", dialog_vars["carrier_planned_jumps"].get())
        apply_manual_planned_distance("carrier", dialog_vars["carrier_planned_distance"].get())

        refresh_active_image_from_mapping("ship")
        refresh_active_image_from_mapping("carrier")
        save_state()
        update_ui_enabled()
        refresh_pref_vars("ship")
        refresh_pref_vars("carrier")
        set_status("Einstellungen gespeichert.")
        dialog.destroy()

    make_button(buttons, text="Speichern", command=save_dialog).grid(row=0, column=0, padx=4)
    make_button(buttons, text="Abbrechen", command=dialog.destroy).grid(row=0, column=1, padx=4)


class ImageMappingTable:
    def __init__(self, parent: Any, image_urls: Dict[str, str]) -> None:
        self.parent = parent
        self.frame = make_frame(parent)
        self.frame.columnconfigure(0, weight=0)
        self.frame.columnconfigure(1, weight=1)
        self.rows: List[Dict[str, Any]] = []
        self.selected_id = ""
        self.next_id = 1
        self.on_select: Optional[Any] = None
        self.name_column_width = table_name_column_width(image_urls)

        self.header_name = make_table_cell(self.frame, "Name", is_header=True)
        apply_table_cell_width(self.header_name, self.name_column_width)
        self.header_name.grid(row=0, column=0, sticky="ew", padx=(0, 1), pady=(0, 1))
        self.header_url = make_table_cell(self.frame, "Bild-URL", is_header=True)
        self.header_url.grid(row=0, column=1, sticky="ew", padx=(1, 0), pady=(0, 1))

        self.body = make_frame(self.frame)
        self.body.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.body.columnconfigure(0, weight=0)
        self.body.columnconfigure(1, weight=1)
        self.filler = make_frame(self.body)
        self.filler.grid(row=0, column=0, columnspan=2, sticky="nsew")
        try:
            self.filler.configure(height=92)
        except Exception:
            pass

    def add_row(self, name: str, image_url: str) -> str:
        item_id = str(self.next_id)
        self.next_id += 1
        row = {"id": item_id, "name": name, "url": image_url, "labels": []}
        self.rows.append(row)
        self.update_name_column_width()
        self.render_rows()
        return item_id

    def set_row(self, item_id: str, name: str, image_url: str) -> None:
        for row in self.rows:
            if row["id"] == item_id:
                row["name"] = name
                row["url"] = image_url
                break
        self.update_name_column_width()
        self.render_rows()

    def delete(self, item_id: str) -> None:
        self.rows = [row for row in self.rows if row["id"] != item_id]
        if self.selected_id == item_id:
            self.selected_id = ""
        self.update_name_column_width()
        self.render_rows()

    def selected_item(self) -> str:
        return self.selected_id

    def selection_set(self, item_id: str) -> None:
        self.selected_id = item_id
        self.render_rows()
        if self.on_select is not None:
            self.on_select()

    def item_values(self, item_id: str) -> tuple:
        for row in self.rows:
            if row["id"] == item_id:
                return str(row["name"]), str(row["url"])
        return "", ""

    def find_by_name(self, name: str) -> str:
        for row in self.rows:
            if str(row["name"]) == name:
                return str(row["id"])
        return ""

    def rows_as_mapping(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for row in self.rows:
            name = str(row["name"]).strip()
            image_url = str(row["url"]).strip()
            if name and image_url:
                mapping[name] = image_url
        return mapping

    def update_name_column_width(self) -> None:
        self.name_column_width = table_name_column_width(
            {str(row["name"]): str(row["url"]) for row in self.rows}
        )
        apply_table_cell_width(self.header_name, self.name_column_width)

    def render_rows(self) -> None:
        for child in self.body.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        if not self.rows:
            self.filler = make_frame(self.body)
            self.filler.grid(row=0, column=0, columnspan=2, sticky="nsew")
            try:
                self.filler.configure(height=92)
            except Exception:
                pass
            return

        for index, row in enumerate(self.rows):
            selected = row["id"] == self.selected_id
            name_label = make_table_cell(self.body, str(row["name"]), is_selected=selected)
            url_label = make_table_cell(self.body, str(row["url"]), is_selected=selected)
            apply_table_cell_width(name_label, self.name_column_width)
            name_label.grid(row=index, column=0, sticky="ew", padx=(0, 1), pady=(0, 1))
            url_label.grid(row=index, column=1, sticky="ew", padx=(1, 0), pady=(0, 1))
            for label in (name_label, url_label):
                label.bind("<Button-1>", lambda _event, item_id=row["id"]: self.selection_set(item_id))

        self.filler = make_frame(self.body)
        self.filler.grid(row=len(self.rows), column=0, columnspan=2, sticky="nsew")
        try:
            self.filler.configure(height=max(18, 92 - len(self.rows) * 24))
        except Exception:
            pass


def make_table_cell(
    parent: Any,
    text: str,
    is_header: bool = False,
    is_selected: bool = False,
) -> Any:
    bg = skin_background(parent)
    fg = skin_foreground(parent, bg)
    if is_header:
        cell_bg = "#101010" if is_dark_color(bg) else "#e6e6e6"
    elif is_selected:
        cell_bg = "#2f5d8c" if is_dark_color(bg) else "#c8ddf2"
        fg = "#ffffff" if is_dark_color(bg) else "#000000"
    else:
        cell_bg = "#111111" if is_dark_color(bg) else "#ffffff"

    label = tk.Label(
        parent,
        text=text,
        anchor="w",
        padx=6,
        pady=3,
        background=cell_bg,
        foreground=readable_foreground(cell_bg, fg),
    )
    return label


def table_name_column_width(image_urls: Dict[str, str]) -> int:
    longest_name = max([len("Name")] + [len(str(name)) for name in image_urls])
    return max(14, min(longest_name + 2, 36))


def apply_table_cell_width(widget: Any, width: int) -> None:
    try:
        widget.configure(width=width)
    except Exception:
        pass


def create_image_table(
    parent: Any,
    start_row: int,
    title: str,
    image_urls: Dict[str, str],
) -> Dict[str, Any]:
    make_label(parent, text=title).grid(
        row=start_row, column=0, columnspan=2, sticky="w", padx=4, pady=(12, 2)
    )

    tree = ImageMappingTable(parent, image_urls)
    tree.frame.grid(row=start_row + 1, column=0, columnspan=2, sticky="nsew", padx=4, pady=2)
    for name, image_url in sorted(image_urls.items()):
        tree.add_row(name, image_url)

    edit_frame = make_frame(parent)
    edit_frame.grid(row=start_row + 2, column=0, columnspan=2, sticky="ew", padx=4, pady=2)
    edit_frame.columnconfigure(1, weight=1)

    name_var = tk.StringVar()
    url_var = tk.StringVar()
    make_label(edit_frame, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
    make_entry(edit_frame, textvariable=name_var, width=24).grid(
        row=0, column=1, sticky="ew", padx=4, pady=2
    )
    make_label(edit_frame, text="Bild-URL").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=2)
    make_entry(edit_frame, textvariable=url_var, width=70).grid(
        row=1, column=1, sticky="ew", padx=4, pady=2
    )

    button_frame = make_frame(parent)
    button_frame.grid(row=start_row + 3, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 6))

    def selected_item() -> str:
        return tree.selected_item()

    def fill_from_selection(_event: Any = None) -> None:
        item_id = selected_item()
        if not item_id:
            return
        name, image_url = tree.item_values(item_id)
        name_var.set(name)
        url_var.set(image_url)

    def change_selected() -> None:
        item_id = selected_item()
        name = name_var.get().strip()
        image_url = url_var.get().strip()
        if not item_id or not name:
            return
        tree.set_row(item_id, name, image_url)

    def add_entry() -> None:
        name = name_var.get().strip()
        image_url = url_var.get().strip()
        if not name:
            return
        existing = find_tree_item_by_name(tree, name)
        if existing:
            tree.set_row(existing, name, image_url)
            tree.selection_set(existing)
        else:
            item_id = tree.add_row(name, image_url)
            tree.selection_set(item_id)

    def delete_selected() -> None:
        item_id = selected_item()
        if not item_id:
            return
        tree.delete(item_id)
        name_var.set("")
        url_var.set("")

    tree.on_select = fill_from_selection
    make_button(button_frame, text="Ändern", command=change_selected).grid(row=0, column=0, padx=(0, 4))
    make_button(button_frame, text="Hinzufügen", command=add_entry).grid(row=0, column=1, padx=4)
    make_button(button_frame, text="Löschen", command=delete_selected).grid(row=0, column=2, padx=4)

    return {"tree": tree, "next_row": start_row + 4}


def find_tree_item_by_name(tree: Any, name: str) -> str:
    if hasattr(tree, "find_by_name"):
        return str(tree.find_by_name(name))

    for item_id in tree.get_children():
        values = tree.item(item_id, "values")
        if values and str(values[0]) == name:
            return str(item_id)
    return ""


def image_mapping_from_tree(tree: Any) -> Dict[str, str]:
    if hasattr(tree, "rows_as_mapping"):
        return tree.rows_as_mapping()

    image_urls: Dict[str, str] = {}
    for item_id in tree.get_children():
        values = tree.item(item_id, "values")
        if len(values) >= 2:
            name = str(values[0]).strip()
            image_url = str(values[1]).strip()
            if name and image_url:
                image_urls[name] = image_url
    return image_urls


def save_dialog_active_image(kind: str, image_url: str) -> None:
    if kind == "ship":
        active_name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
        if active_name and image_url:
            get_ship_image_urls()[active_name] = image_url
    else:
        active_name = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "")
        if active_name and image_url:
            get_carrier_image_urls()[active_name] = image_url


def add_image_mapping_rows(
    frame: Any,
    start_row: int,
    title: str,
    image_urls: Dict[str, str],
    variables: Dict[str, Any],
) -> int:
    make_label(frame, text=title).grid(
        row=start_row, column=0, columnspan=2, sticky="w", padx=4, pady=(10, 2)
    )
    row_index = start_row + 1

    if not image_urls:
        make_label(frame, text="Keine gespeicherten Einträge").grid(
            row=row_index, column=0, columnspan=2, sticky="w", padx=4, pady=2
        )
        return row_index + 1

    for name in sorted(image_urls):
        image_url = str(image_urls.get(name) or "")
        variable = tk.StringVar(value=image_url)
        variables[name] = variable
        make_label(frame, text=name).grid(row=row_index, column=0, sticky="w", padx=4, pady=2)
        entry = make_entry(frame, textvariable=variable, width=60)
        entry.grid(row=row_index, column=1, sticky="ew", padx=4, pady=2)
        pref_controls.append(entry)
        row_index += 1

    return row_index


def make_frame(parent: Any) -> Any:
    widget = tk.Frame(parent, borderwidth=0, highlightthickness=0)
    apply_skin(widget, parent, "frame")
    return widget


def make_label(parent: Any, **kwargs: Any) -> Any:
    widget = tk.Label(parent, **kwargs)
    apply_skin(widget, parent, "label")
    return widget


def make_status_label(parent: Any, **kwargs: Any) -> Any:
    widget = tk.Label(parent, anchor="w", **kwargs)
    apply_skin(widget, parent, "status")
    return widget


def make_entry(parent: Any, **kwargs: Any) -> Any:
    widget = tk.Entry(parent, **kwargs)
    apply_skin(widget, parent, "entry")
    return widget


def make_button(parent: Any, **kwargs: Any) -> Any:
    command = kwargs.pop("command", None)
    widget = tk.Label(parent, anchor="center", padx=8, pady=4, cursor="hand2", **kwargs)
    widget._drt_command = command
    widget._drt_enabled = True
    widget.bind("<Button-1>", clickable_label_clicked)
    widget.bind("<Enter>", clickable_label_entered)
    widget.bind("<Leave>", clickable_label_left)
    apply_skin(widget, parent, "button")
    return widget


def make_checkbutton(parent: Any, **kwargs: Any) -> Any:
    widget = tk.Checkbutton(parent, anchor="w", padx=4, pady=2, **kwargs)
    apply_skin(widget, parent, "checkbutton")
    try:
        widget.configure(borderwidth=0, highlightthickness=0)
    except Exception:
        pass
    return widget


def clickable_label_clicked(event: Any) -> None:
    widget = event.widget
    if not getattr(widget, "_drt_enabled", True):
        return
    command = getattr(widget, "_drt_command", None)
    if command is not None:
        command()


def clickable_label_entered(event: Any) -> None:
    widget = event.widget
    if not getattr(widget, "_drt_enabled", True):
        return
    apply_skin(widget, widget.master, "button_hover")


def clickable_label_left(event: Any) -> None:
    widget = event.widget
    apply_skin(widget, widget.master, "button")


def apply_skin(widget: Any, parent: Any, role: str) -> None:
    bg = skin_background(parent)
    fg = skin_foreground(parent, bg)
    entry_bg = "#111111" if is_dark_color(bg) else "#ffffff"
    button_bg = "#101010" if is_dark_color(bg) else inherited_color(widget, ("background", "bg")) or bg
    active_bg = "#202020" if is_dark_color(bg) else button_bg
    border_color = "#343434" if is_dark_color(bg) else "#b8b8b8"
    button_fg = readable_foreground(button_bg, fg)
    if getattr(widget, "_drt_enabled", True) is False:
        button_fg = "#777777" if is_dark_color(bg) else "#888888"

    options: Dict[str, Any] = {}
    if role == "frame":
        options = {"background": bg}
    elif role == "label":
        options = {"background": bg, "foreground": fg}
    elif role == "status":
        options = {"background": bg, "foreground": readable_foreground(bg, fg)}
    elif role == "checkbutton":
        options = {
            "background": bg,
            "foreground": fg,
            "activebackground": bg,
            "activeforeground": fg,
            "selectcolor": "#101010" if is_dark_color(bg) else "#ffffff",
            "highlightbackground": bg,
        }
    elif role == "entry":
        options = {
            "background": entry_bg,
            "foreground": fg,
            "insertbackground": fg,
            "disabledbackground": entry_bg,
            "disabledforeground": fg,
            "highlightbackground": bg,
            "highlightcolor": "#343434" if is_dark_color(bg) else "#b8b8b8",
            "highlightthickness": 1,
            "relief": "solid",
            "bd": 1,
        }
    elif role in ("button", "button_hover"):
        chosen_bg = active_bg if role == "button_hover" else button_bg
        options = {
            "background": chosen_bg,
            "foreground": button_fg,
            "activebackground": active_bg,
            "activeforeground": button_fg,
            "highlightbackground": border_color,
            "highlightcolor": border_color,
            "highlightthickness": 1,
            "bd": 1,
            "relief": "solid",
        }

    for option, value in options.items():
        try:
            widget.configure(**{option: value})
        except Exception:
            pass


def apply_treeview_skin(parent: Any) -> str:
    style_name = "DiscordRouteTracker.Treeview"
    if ttk is None:
        return style_name

    bg = skin_background(parent)
    fg = skin_foreground(parent, bg)
    field_bg = "#111111" if is_dark_color(bg) else "#ffffff"
    heading_bg = "#101010" if is_dark_color(bg) else "#e6e6e6"
    selected_bg = "#2f5d8c" if is_dark_color(bg) else "#c8ddf2"
    selected_fg = "#ffffff" if is_dark_color(bg) else "#000000"

    try:
        style = ttk.Style()
        style.configure(
            style_name,
            background=field_bg,
            fieldbackground=field_bg,
            foreground=fg,
            bordercolor=bg,
            lightcolor=bg,
            darkcolor=bg,
            rowheight=22,
        )
        style.configure(
            f"{style_name}.Heading",
            background=heading_bg,
            foreground=fg,
            relief="flat",
        )
        style.map(
            style_name,
            background=[("selected", selected_bg)],
            foreground=[("selected", selected_fg)],
        )
    except Exception:
        pass
    return style_name


def configure_treeview_item_tags(tree: Any, parent: Any) -> None:
    bg = skin_background(parent)
    fg = skin_foreground(parent, bg)
    field_bg = "#111111" if is_dark_color(bg) else "#ffffff"
    try:
        tree.tag_configure("normal", background=field_bg, foreground=fg)
    except Exception:
        pass


def inherited_color(widget: Any, option_names: tuple) -> str:
    current = widget
    while current is not None:
        for option in option_names:
            try:
                value = str(current.cget(option))
                if value:
                    return value
            except Exception:
                pass
        try:
            current = current.master
        except Exception:
            return ""
    return ""


def skin_background(widget: Any) -> str:
    color = inherited_color(widget, ("background", "bg"))
    style_color = ttk_style_color("TFrame", "background")

    if is_usable_color(style_color) and is_dark_color(style_color):
        return style_color
    if is_usable_color(color):
        return color
    if is_usable_color(style_color):
        return style_color

    return "#000000"


def skin_foreground(widget: Any, background: str) -> str:
    color = inherited_color(widget, ("foreground", "fg"))
    if is_usable_color(color):
        return readable_foreground(background, color)

    style_color = ttk_style_color("TLabel", "foreground")
    if is_usable_color(style_color):
        return readable_foreground(background, style_color)

    return "#ffffff" if is_dark_color(background) else "#000000"


def ttk_style_color(style_name: str, option: str) -> str:
    if ttk is None:
        return ""
    try:
        return str(ttk.Style().lookup(style_name, option) or "")
    except Exception:
        return ""


def is_usable_color(color: str) -> bool:
    if not color:
        return False
    if color.startswith("#"):
        return color_luminance(color) is not None
    return not color.lower().startswith("system")


def readable_foreground(background: str, preferred: str) -> str:
    if not colors_are_too_close(background, preferred):
        return preferred
    return "#ffffff" if is_dark_color(background) else "#000000"


def colors_are_too_close(first: str, second: str) -> bool:
    first_luminance = color_luminance(first)
    second_luminance = color_luminance(second)
    if first_luminance is None or second_luminance is None:
        return False
    return abs(first_luminance - second_luminance) < 32


def color_luminance(color: str) -> Optional[float]:
    if not color or not color.startswith("#"):
        return None
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(channel * 2 for channel in value)
    if len(value) != 6:
        return None
    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except ValueError:
        return None
    return red * 0.299 + green * 0.587 + blue * 0.114


def is_dark_color(color: str) -> bool:
    luminance = color_luminance(color)
    if luminance is None:
        return True
    return luminance < 128


def apply_pref_vars() -> None:
    """Copy Tk preference variables into state when the preferences UI exists."""
    if plugin_enabled_var is not None:
        state["plugin_enabled"] = bool(plugin_enabled_var.get())
    if ship_poster_name_var is not None:
        state["ship"]["poster_name"] = ship_poster_name_var.get().strip()
    if ship_webhook_var is not None:
        state["ship"]["webhook_url"] = ship_webhook_var.get().strip()
    if ship_target_var is not None:
        state["ship"]["target_system"] = ship_target_var.get().strip()
    if ship_image_mapping_tree is not None:
        state["ship"]["image_urls_by_ship"] = image_mapping_from_tree(ship_image_mapping_tree)
    else:
        apply_image_mapping_vars("ship", ship_image_mapping_vars)
    if ship_image_var is not None:
        image_url = ship_image_var.get().strip()
        active_ship_name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
        if image_url:
            save_image_url_for_active_ship(image_url)
        state["ship"]["image_url"] = get_ship_image_urls().get(active_ship_name, "")
    if ship_planned_jumps_var is not None:
        apply_manual_planned_jumps("ship", ship_planned_jumps_var.get())
    if ship_planned_distance_var is not None:
        apply_manual_planned_distance("ship", ship_planned_distance_var.get())
    if carrier_poster_name_var is not None:
        state["carrier"]["poster_name"] = carrier_poster_name_var.get().strip()
    if carrier_webhook_var is not None:
        state["carrier"]["webhook_url"] = carrier_webhook_var.get().strip()
    if carrier_target_var is not None:
        state["carrier"]["target_system"] = carrier_target_var.get().strip()
    if carrier_image_mapping_tree is not None:
        state["carrier"]["image_urls_by_carrier"] = image_mapping_from_tree(carrier_image_mapping_tree)
    else:
        apply_image_mapping_vars("carrier", carrier_image_mapping_vars)
    if carrier_image_var is not None:
        image_url = carrier_image_var.get().strip()
        active_carrier_name = current_carrier_name or str(
            state["carrier"].get("active_carrier_name") or ""
        )
        if image_url:
            save_image_url_for_active_carrier(image_url)
        state["carrier"]["image_url"] = get_carrier_image_urls().get(active_carrier_name, "")
    if carrier_planned_jumps_var is not None:
        apply_manual_planned_jumps("carrier", carrier_planned_jumps_var.get())
    if carrier_planned_distance_var is not None:
        apply_manual_planned_distance("carrier", carrier_planned_distance_var.get())
    refresh_active_image_from_mapping("ship")
    refresh_active_image_from_mapping("carrier")


def apply_image_mapping_vars(kind: str, variables: Dict[str, Any]) -> None:
    image_urls = get_ship_image_urls() if kind == "ship" else get_carrier_image_urls()
    for name, variable in variables.items():
        image_url = variable.get().strip()
        if image_url:
            image_urls[name] = image_url
        else:
            image_urls.pop(name, None)


def refresh_active_image_from_mapping(kind: str) -> None:
    if kind == "ship":
        name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
        image_url = get_ship_image_urls().get(name)
        if image_url is not None:
            state["ship"]["image_url"] = image_url
            if ship_image_var is not None:
                ship_image_var.set(image_url)
    else:
        name = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "")
        image_url = get_carrier_image_urls().get(name)
        if image_url is not None:
            state["carrier"]["image_url"] = image_url
            if carrier_image_var is not None:
                carrier_image_var.set(image_url)


def update_active_ship(entry: Dict[str, Any], state_data: Dict[str, Any]) -> None:
    """Track EDMC's current ship name and apply its stored image URL."""
    global current_ship_name

    if state_data is None:
        state_data = {}

    ship_name = extract_ship_name(entry, state_data)
    if not ship_name or ship_name == current_ship_name:
        return

    previous_ship_name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
    current_ship_name = ship_name
    state["ship"]["active_ship_name"] = ship_name
    if active_ship_label_var is not None:
        active_ship_label_var.set(active_vehicle_text("ship"))

    image_urls = get_ship_image_urls()
    image_url = image_urls.get(ship_name)
    if image_url is None and not previous_ship_name and state["ship"].get("image_url"):
        image_url = str(state["ship"].get("image_url") or "")
        image_urls[ship_name] = image_url
    elif image_url is None:
        image_url = ""
        set_status(f"Warnung: Kein Schiffbild für {ship_name} gespeichert.")

    if state["ship"].get("image_url") != image_url:
        state["ship"]["image_url"] = image_url
        if ship_image_var is not None:
            ship_image_var.set(image_url)

    save_state()


def update_active_carrier(entry: Dict[str, Any], state_data: Dict[str, Any]) -> None:
    """Track the carrier name EDMC exposes in state or carrier journal events."""
    global current_carrier_name

    if state_data is None:
        state_data = {}

    carrier_name = extract_carrier_name(entry, state_data)
    if not carrier_name or carrier_name == current_carrier_name:
        return

    previous_carrier_name = current_carrier_name or str(
        state["carrier"].get("active_carrier_name") or ""
    )
    current_carrier_name = carrier_name
    state["carrier"]["active_carrier_name"] = carrier_name
    if active_carrier_label_var is not None:
        active_carrier_label_var.set(active_vehicle_text("carrier"))
    image_urls = get_carrier_image_urls()
    image_url = image_urls.get(carrier_name)
    if image_url is None and not previous_carrier_name and state["carrier"].get("image_url"):
        image_url = str(state["carrier"].get("image_url") or "")
        image_urls[carrier_name] = image_url
    elif image_url is None:
        image_url = ""
    if state["carrier"].get("image_url") != image_url:
        state["carrier"]["image_url"] = image_url
        if carrier_image_var is not None:
            carrier_image_var.set(image_url)
    save_state()


def extract_ship_name(entry: Dict[str, Any], state_data: Dict[str, Any]) -> str:
    """Return the ship name EDMC is likely showing, with sensible fallbacks."""
    candidates = [
        state_data.get("ShipName"),
        entry.get("ShipName"),
        state_data.get("ship_name"),
        entry.get("Ship"),
        state_data.get("ShipType"),
        entry.get("ShipType"),
    ]

    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text

    return str(state["ship"].get("active_ship_name") or "").strip()


def extract_carrier_name(entry: Dict[str, Any], state_data: Dict[str, Any]) -> str:
    """Return the current carrier name if EDMC has exposed one."""
    candidates = [
        state_data.get("CarrierName"),
        state_data.get("FleetCarrierName"),
        state_data.get("carrier_name"),
        entry.get("CarrierName"),
        entry.get("FleetCarrierName"),
        entry.get("Name") if entry.get("event") in ("CarrierStats", "CarrierJump") else None,
        entry.get("Callsign") if entry.get("event") in ("CarrierStats", "CarrierJump") else None,
    ]

    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text

    return str(state["carrier"].get("active_carrier_name") or "").strip()


def get_current_ship_image_url() -> str:
    ship_name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
    if ship_name:
        mapped_url = get_ship_image_urls().get(ship_name)
        if mapped_url is not None:
            state["ship"]["image_url"] = mapped_url
            return str(mapped_url)
    state["ship"]["image_url"] = ""
    return ""


def get_current_carrier_image_url() -> str:
    carrier_name = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "")
    if carrier_name:
        mapped_url = get_carrier_image_urls().get(carrier_name)
        if mapped_url is not None:
            state["carrier"]["image_url"] = mapped_url
            return str(mapped_url)
    state["carrier"]["image_url"] = ""
    return ""


def save_image_url_for_active_ship(image_url: str) -> None:
    ship_name = current_ship_name or str(state["ship"].get("active_ship_name") or "")
    if not ship_name:
        return

    image_urls = get_ship_image_urls()
    if image_url:
        image_urls[ship_name] = image_url
    else:
        image_urls.pop(ship_name, None)


def save_image_url_for_active_carrier(image_url: str) -> None:
    carrier_name = current_carrier_name or str(state["carrier"].get("active_carrier_name") or "")
    if not carrier_name:
        return

    image_urls = get_carrier_image_urls()
    if image_url:
        image_urls[carrier_name] = image_url
    else:
        image_urls.pop(carrier_name, None)


def get_ship_image_urls() -> Dict[str, str]:
    image_urls = state["ship"].setdefault("image_urls_by_ship", {})
    if not isinstance(image_urls, dict):
        image_urls = {}
        state["ship"]["image_urls_by_ship"] = image_urls
    return image_urls


def get_carrier_image_urls() -> Dict[str, str]:
    image_urls = state["carrier"].setdefault("image_urls_by_carrier", {})
    if not isinstance(image_urls, dict):
        image_urls = {}
        state["carrier"]["image_urls_by_carrier"] = image_urls
    return image_urls


def webhook_with_wait(webhook_url: str) -> str:
    """Return a webhook URL that asks Discord to include the created message."""
    parts = urlsplit(webhook_url)
    query_parts = [part for part in parts.query.split("&") if part]
    if not any(part == "wait=true" or part.startswith("wait=") for part in query_parts):
        query_parts.append("wait=true")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query_parts), parts.fragment))


def webhook_message_url(webhook_url: str, message_id: str) -> str:
    """Return Discord's edit URL for a previously created webhook message."""
    parts = urlsplit(webhook_url)
    path = f"{parts.path.rstrip('/')}/messages/{message_id}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", parts.fragment))


def discord_error_detail(response: Any) -> str:
    if response is None:
        return ""
    try:
        text = str(response.text or "").strip()
    except Exception:
        return ""
    if not text:
        return ""
    return f" | Discord: {text[:300]}"


def is_http_url(value: str) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def normalize_pos(value: Any) -> Optional[List[float]]:
    """Validate and normalize an ED journal StarPos value."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None

    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None


def field_value(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "-"


def system_field_value(value: Any) -> str:
    text = field_value(value)
    return f"```\n{text}\n```" if text != "-" else text


def journal_timestamp(entry: Dict[str, Any]) -> str:
    timestamp = str(entry.get("timestamp") or "").strip()
    if timestamp_to_datetime(timestamp) is not None:
        return timestamp
    return current_utc_timestamp()


def current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_field_value(value: Any) -> str:
    dt_value = timestamp_to_datetime(str(value or "").strip())
    if dt_value is None:
        return "-"
    unix_time = int(dt_value.timestamp())
    return f"<t:{unix_time}:d> <t:{unix_time}:t>"


def timestamp_to_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        dt_value = datetime.fromisoformat(text)
    except ValueError:
        return None

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)


def normalize_route_systems(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []

    systems: List[str] = []
    for item in value:
        system_name = str(item or "").strip()
        if not system_name:
            continue
        if systems and same_system(systems[-1], system_name):
            continue
        systems.append(system_name)
    return systems


def append_route_system(kind: str, system_name: str) -> None:
    if kind not in TRACKER_KINDS:
        return

    system_name = str(system_name or "").strip()
    if not system_name:
        return

    tracker = state[kind]
    systems = normalize_route_systems(tracker.get("route_systems"))
    if not systems:
        start_system = str(tracker.get("start_system") or "").strip()
        if start_system:
            systems.append(start_system)

    if any(same_system(existing, system_name) for existing in systems):
        tracker["route_systems"] = systems
        return

    systems.append(system_name)
    tracker["route_systems"] = systems


def route_embed_fields(kind: str) -> List[Dict[str, Any]]:
    systems = route_systems_for_embed(kind)
    if not systems:
        return [{"name": "Route", "value": "-", "inline": False}]

    parts = chunk_route_systems(systems)
    fields: List[Dict[str, Any]] = []
    for index, part in enumerate(parts):
        name = "Route" if len(parts) == 1 else f"Route {index + 1}/{len(parts)}"
        fields.append(
            {
                "name": name,
                "value": f"```\n{' -> '.join(part)}\n```",
                "inline": False,
            }
        )
    return fields


def chunk_route_systems(systems: List[str]) -> List[List[str]]:
    chunks: List[List[str]] = []
    current: List[str] = []
    current_length = len("```\n\n```")
    separator_length = len(" -> ")
    max_field_length = 1000

    for system_name in systems:
        item_length = len(system_name)
        extra = item_length if not current else separator_length + item_length
        if current and current_length + extra > max_field_length:
            chunks.append(current)
            current = [system_name]
            current_length = len("```\n\n```") + item_length
        else:
            current.append(system_name)
            current_length += extra

    if current:
        chunks.append(current)
    return chunks


def route_systems_for_embed(kind: str) -> List[str]:
    if kind not in TRACKER_KINDS:
        return []

    tracker = state[kind]
    systems = normalize_route_systems(tracker.get("route_systems"))
    start_system = str(tracker.get("start_system") or "").strip()
    current_system = str(tracker.get("current_system") or "").strip()
    target_system = str(tracker.get("target_system") or "").strip()

    if start_system and not any(same_system(item, start_system) for item in systems):
        systems.insert(0, start_system)
    if current_system and not any(same_system(item, current_system) for item in systems):
        systems.append(current_system)
    if target_system and not any(same_system(item, target_system) for item in systems):
        systems.append(target_system)

    return systems


def int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def set_status(message: str) -> None:
    """Update the EDMC status label if it exists."""
    try:
        if status_var is not None:
            status_var.set(message)
        if status_label_widget is not None:
            apply_skin(status_label_widget, status_label_widget.master, "status")
    except Exception:
        pass
