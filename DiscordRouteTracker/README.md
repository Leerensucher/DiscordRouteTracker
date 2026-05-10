# DiscordRouteTracker

EDMC plugin for Discord route progress embeds for ship and fleet carrier routes.

## Version

Current plugin version: `0.1.1`

## Updates

The plugin contains a manifest-based update routine. It reads
`update_manifest.json` from the GitHub `main` branch and updates `load.py` when
the manifest version is newer than `PLUGIN_VERSION`.

The updater currently only replaces `load.py`, writes a `.bak` backup first, and
requires an EDMC restart after installation.
