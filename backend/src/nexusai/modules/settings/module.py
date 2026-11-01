import json

from nexusai.contracts.settings import (
    GetProfile,
    GetSettings,
    Profile,
    ProfileChanged,
    Settings,
    SettingsChanged,
    UpdateSettings,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context, Module

settings_module = Module(
    name="settings",
    migrations=[
        Migration(
            "settings_001",
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        ),
        Migration(
            "settings_002",
            "CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL)",
        ),
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


def _load_profile(ctx: Context) -> Profile:
    rows = ctx.bus.db.fetch_all("SELECT value FROM profile")
    return Profile.model_validate_json(rows[0]["value"]) if rows else Profile()


@settings_module.query("profile.get")
def get_profile(query: GetProfile, ctx: Context) -> Profile:
    return _load_profile(ctx)


@settings_module.command("profile.update")
def update_profile(command: Profile, ctx: Context) -> Profile:
    before = _load_profile(ctx).model_dump()
    changed = [key for key, value in command.model_dump().items() if before[key] != value]
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO profile (id, value) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET value = excluded.value",
            (command.model_dump_json(),),
        )
        if changed:
            work.emit(
                "profile.changed",
                ProfileChanged(fields=changed).model_dump(),
                source=settings_module.name,
                trace_id=ctx.trace_id,
            )
    return command
