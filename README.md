# Katha local archive

## Run

From this folder, start the local API and website:

```powershell
python server.py
```

Then open http://127.0.0.1:8000. The server uses only Python's standard library. SQLite data is stored in `katha.sqlite3`; optional uploads are stored in `uploads/`. The sample stories are added once to a new database.

Set `KATHA_PORT` or `KATHA_DATABASE` before starting the server to change the port or database path.

## Prototype limits

This service binds to localhost and has no accounts, moderation dashboard, backup, or deployment security. Anyone using the local service can read submitted stories. Do not publish sensitive or restricted knowledge here. Before a community deployment, add keeper-controlled consent and withdrawal, reviewer roles, access rules for sensitive entries, backups, and a production-grade hosting setup.