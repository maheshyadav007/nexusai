import json

from nexusai.contracts.settings import GetSettings, Settings, SettingsChanged, UpdateSettings
from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context, Module

settings_module = Module(
    name="settings",
    migrations=[
        Migration(
            "settings_001",
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        )
    ],
)


def _load(ctx: Context) -> Settings:
    rows = ctx.bus.db.fetch_all("SELECT key, value FROM settings")
    stored = {row["key"]: json.loads(row["value"]) for row in rows}
    return Settings(**{**ctx.config.default_settings, **stored})


@settings_module.query("settings.get")
def get_settings(query: GetSettings, ctx: Context) -> Settings:
    return _load(ctx)


@settings_module.command("settings.update")
def update_settings(command: UpdateSettings, ctx: Context) -> Settings:
    changes = command.model_dump(exclude_none=True)
    with ctx.bus.unit_of_work() as work:
        for key, value in changes.items():
            work.tx.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        if changes:
            work.emit(
                "settings.changed",
                SettingsChanged(changed=changes).model_dump(),
                source=settings_module.name,
                trace_id=ctx.trace_id,
            )
    return _load(ctx)
