"""Installing plugins: skills and the MCP servers they need, from one folder, reviewed as one.

A plugin is read in Claude Code's layout (`plugin.json` at the root, in `.claude-plugin/` or in
`.codex-plugin/`; `skills/<name>/SKILL.md`; `.mcp.json` or `mcp.json`, or `mcpServers` in the
manifest). Nothing in it runs. Each skill becomes a skill proposal the person reads in full on the
Skills page; each remote MCP server is added as a connector when the person says so, with its tool
list checked as any connector's is. What would run code on this computer (local servers, hooks,
commands, binaries) is listed as not used here. Secrets never live in a plugin: a header written
out in it is refused, and `${user_config.KEY}` asks for the value when its servers are added.
See docs/PLUGINS_PLAN.md and docs/PLUGIN_FORMAT_PLAN.md.
"""

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from nexusai.contracts.agent import InstalledPlugin, InstallResult, PluginList, PluginServer
from nexusai.contracts.connectors import AddConnector, ConnectorAction, Connectors, GetConnectors
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import skills
from nexusai.modules.connectors import module as connectors

MIGRATION = Migration(
    "agent_plugin_installs_001",
    """
CREATE TABLE plugin_installs (
  name TEXT PRIMARY KEY, display_name TEXT NOT NULL, version TEXT NOT NULL, description TEXT NOT NULL,
  source TEXT NOT NULL, skills TEXT NOT NULL, proposals TEXT NOT NULL, servers TEXT NOT NULL,
  connectors TEXT NOT NULL DEFAULT '[]', skipped TEXT NOT NULL, created TEXT NOT NULL);
""",
)
MANIFESTS = ("plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
MCP_FILES = (".mcp.json", "mcp.json")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SETTING = re.compile(r"^\$\{(?:user_config\.)?([A-Za-z_][A-Za-z0-9_]*)\}$")
# The transports in standard MCP settings, as NexusAI reaches them.
TRANSPORTS = {"http": "http", "streamable-http": "http", "streamablehttp": "http", "sse": "sse"}
MOST_TIMEOUT_SECONDS = 600
# Parts other tools' plugins carry that NexusAI doesn't run, by the folder or file they live in.
NOT_USED = {
    "agents": "Agents",
    "commands": "Commands",
    "hooks": "Hooks",
    "bin": "Programs",
    "monitors": "Monitors",
    "output-styles": "Output styles",
    ".lsp.json": "Language servers",
}
MOST_FILES = 300
MOST_BYTES = 3_000_000
FETCH_SECONDS = 20


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(path: str) -> bool:
    name = PurePosixPath(path)
    return name.suffix.lower() in skills.TEXT_SUFFIXES or name.name in MCP_FILES


def _from_zip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        # A zip of a folder has the folder's name in front of everything.
        roots = {PurePosixPath(n).parts[0] for n in names if len(PurePosixPath(n).parts) > 1}
        strip = next(iter(roots)) if len(roots) == 1 and all("/" in n for n in names) else None
        found: dict[str, str] = {}
        for name in names:
            relative = name.split("/", 1)[1] if strip else name
            if ".." in PurePosixPath(relative).parts or not _text(relative):
                continue
            try:
                found[relative] = archive.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
            if len(found) >= MOST_FILES:
                break
        return found


def _from_github(
    client: httpx.Client, owner: str, repo: str, ref: str, path: str
) -> dict[str, str]:
    found: dict[str, str] = {}

    def walk(folder: str, prefix: str, depth: int) -> None:
        listing = skills._get(
            client, f"https://api.github.com/repos/{owner}/{repo}/contents/{folder}?ref={ref}"
        ).json()
        for item in listing if isinstance(listing, list) else []:
            if len(found) >= MOST_FILES:
                return
            name = f"{prefix}{item['name']}"
            if item["type"] == "dir" and depth < 5:
                walk(item["path"], f"{name}/", depth + 1)
            elif item["type"] == "file" and _text(name):
                try:
                    found[name] = skills._get(client, item["download_url"]).content.decode("utf-8")
                except UnicodeDecodeError:
                    continue

    walk(path, "", 0)
    return found


def _from_folder(folder: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        if len(found) >= MOST_FILES:
            break
        relative = path.relative_to(folder).as_posix()
        if not path.is_file() or path.is_symlink() or not _text(relative):
            continue
        try:
            found[relative] = path.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return found


def fetch(source: str) -> dict[str, str]:
    """A plugin's text files from a GitHub folder, a zip address, a folder on this computer, or a
    single MCP settings file (.mcp.json or mcp.json, as other apps write them)."""
    text = source.strip()
    local = Path(text).expanduser()
    if text.startswith(("/", "~")) or (len(text) > 2 and text[1] == ":"):
        if local.is_file() and local.suffix.lower() == ".json":
            try:
                return {MCP_FILES[0]: local.read_text("utf-8")}
            except (UnicodeDecodeError, OSError) as error:
                raise CommandError("plugin.fetch", f"{text} can't be read.", 422) from error
        if not local.is_dir():
            raise CommandError(
                "plugin.fetch", f"There's no folder or settings file at {text}.", 422
            )
        return _from_folder(local)
    parsed = urlparse(text)
    if parsed.scheme != "https":
        raise CommandError(
            "plugin.fetch", "Give an https link (a GitHub folder or a zip) or a folder path.", 422
        )
    with httpx.Client(timeout=FETCH_SECONDS, follow_redirects=True) as client:
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc == "github.com" and len(parts) >= 2:
            owner, repo, *rest = parts
            ref, path = ("HEAD", "")
            if len(rest) >= 2 and rest[0] == "tree":
                ref, path = rest[1], "/".join(rest[2:])
            return _from_github(client, owner, repo, ref, path)
        response = skills._get(client, text)
        if len(response.content) > MOST_BYTES:
            raise CommandError("plugin.fetch", "That's larger than a plugin should be (3 MB).", 422)
        if response.content[:2] != b"PK":
            raise CommandError("plugin.fetch", "That link isn't a zip or a GitHub folder.", 422)
        return _from_zip(response.content)


def _slug(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return words[:64].strip("-") or "plugin"


def _manifest(files: dict[str, str], fallback: str = "") -> dict[str, Any]:
    for path in MANIFESTS:
        if path in files:
            try:
                found = json.loads(files[path])
            except json.JSONDecodeError as error:
                raise CommandError("plugin.invalid", f"{path} isn't valid JSON.", 422) from error
            if not isinstance(found, dict):
                raise CommandError("plugin.invalid", f"{path} isn't a JSON object.", 422)
            return found
    has_servers = any(path in files for path in MCP_FILES)
    has_skills = any(PurePosixPath(p).parts[:1] == ("skills",) for p in files)
    if (has_servers or has_skills) and fallback:
        # MCP settings or skills without a manifest, as many folders are: named after the folder.
        return {"name": _slug(fallback), "displayName": fallback}
    raise CommandError(
        "plugin.invalid",
        "It has no plugin.json, MCP settings (.mcp.json) or skills folder, so there's nothing to"
        " install. A skill alone is added as a skill.",
        422,
    )


def _servers(files: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for path in MCP_FILES:
        if path in files:
            try:
                parsed = json.loads(files[path])
            except json.JSONDecodeError as error:
                raise CommandError("plugin.invalid", f"{path} isn't valid JSON.", 422) from error
            servers = parsed.get("mcpServers", parsed) if isinstance(parsed, dict) else {}
            found.update(servers if isinstance(servers, dict) else {})
    inline = manifest.get("mcpServers")
    if isinstance(inline, dict):
        found.update(inline)
    return found


def standard_server(
    name: str, raw: Any, *, secrets_allowed: bool
) -> tuple[PluginServer | None, str | None]:
    """One server from standard MCP settings (type, url, headers, timeout), or why it isn't used.

    From a plugin, a header must ask for its value (${user_config.KEY}); from the person, the
    values they gave are used as they are. A server that runs a program on this computer (stdio,
    command, args, env) or speaks WebSocket isn't used here yet."""
    if not isinstance(raw, dict):
        return None, f"MCP server {name}: not a server description"
    kind = str(raw.get("type") or ("stdio" if raw.get("command") else "http")).casefold()
    if kind == "stdio" or raw.get("command"):
        return (
            None,
            f"MCP server {name}: it runs a program on this computer, which isn't used here yet",
        )
    if kind not in TRANSPORTS:
        return None, f"MCP server {name}: its {kind} transport isn't supported here"
    url = str(raw.get("url") or "")
    if not url.startswith(("https://", "http://")):
        return None, f"MCP server {name}: it has no web address"
    needs: list[str] = []
    given = raw.get("headers")
    headers: dict[str, str] = {
        str(k): str(v) for k, v in (given if isinstance(given, dict) else {}).items()
    }
    for header, value in headers.items():
        match = SETTING.match(value.strip())
        if match:
            needs.append(match.group(1))
        elif not secrets_allowed:
            raise CommandError(
                "plugin.secret",
                f"MCP server {name} has a value written into its {header} header. A plugin must"
                " ask for secrets instead, so it isn't installed.",
                422,
            )
    timeout = raw.get("timeout")
    seconds = (
        max(1, min(MOST_TIMEOUT_SECONDS, round(timeout / 1000)))
        if isinstance(timeout, int | float) and timeout > 0
        else None
    )
    return (
        PluginServer(
            name=name,
            url=url,
            headers=headers,
            needs=needs,
            transport="sse" if TRANSPORTS[kind] == "sse" else "http",
            timeout_seconds=seconds,
        ),
        None,
    )


def _server(name: str, raw: Any) -> tuple[PluginServer | None, str | None]:
    return standard_server(name, raw, secrets_allowed=False)


def servers_in(text: str) -> dict[str, Any]:
    """The servers in pasted MCP settings: an mcpServers block, servers by name, or one server."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandError("mcp.settings", "Those settings aren't valid JSON.", 422) from error
    if not isinstance(parsed, dict):
        raise CommandError("mcp.settings", "Those settings aren't a JSON object.", 422)
    if isinstance(parsed.get("mcpServers"), dict):
        return dict(parsed["mcpServers"])
    if "url" in parsed or "command" in parsed or "type" in parsed:
        return {"server": parsed}
    return parsed


def connector_for(server: PluginServer, values: dict[str, str]) -> AddConnector:
    """What adds a server as a connector: its headers with their values, a bearer token as the
    token, and how it's reached."""
    headers: dict[str, str] = {}
    token = None
    for header, value in server.headers.items():
        match = SETTING.match(value.strip())
        actual = values.get(match.group(1), "") if match else value
        if header.casefold() == "authorization" and actual.startswith("Bearer "):
            token = actual.removeprefix("Bearer ").strip()
        else:
            headers[header] = actual
    return AddConnector(
        name=server.name[:60],
        url=server.url,
        audience="internal",
        token=token,
        headers=headers,
        transport=server.transport,
        timeout_seconds=server.timeout_seconds,
    )


def read(
    files: dict[str, str], fallback: str = ""
) -> tuple[dict[str, Any], dict[str, dict[str, str]], list[PluginServer], list[str]]:
    """What's in a plugin: its manifest, its skills' files, its remote servers, and what isn't used."""
    manifest = _manifest(files, fallback)
    given = str(manifest.get("name") or fallback).strip()
    name = given if NAME.match(given) else _slug(given)
    if not given or not NAME.match(name):
        raise CommandError("plugin.invalid", "It has no name that can be used.", 422)
    if name != given:
        # "Sensing Agent" or "sensing_agent" becomes sensing-agent, the shape plugin names take,
        # and keeps the name it was given to show.
        manifest = {**manifest, "name": name, "displayName": manifest.get("displayName") or given}
    found_skills: dict[str, dict[str, str]] = {}
    for path, text in files.items():
        parts = PurePosixPath(path).parts
        if len(parts) >= 3 and parts[0] == "skills":
            found_skills.setdefault(parts[1], {})["/".join(parts[2:])] = text
    found_skills = {k: v for k, v in found_skills.items() if skills.ENTRY in v}
    servers, skipped = [], []
    for server_name, raw in _servers(files, manifest).items():
        server, why = _server(str(server_name), raw)
        if server:
            servers.append(server)
        if why:
            skipped.append(why)
    tops = {PurePosixPath(path).parts[0] for path in files}
    skipped += [label for part, label in NOT_USED.items() if part in tops]
    if not found_skills and not servers:
        raise CommandError("plugin.empty", "It has no skills or remote MCP servers to add.", 422)
    return manifest, found_skills, servers, skipped


def _name_of(source: str) -> str:
    """What to call a plugin with no manifest: its folder, or the folder its settings file is in."""
    text = source.strip().rstrip("/")
    path = PurePosixPath(urlparse(text).path if "://" in text else text)
    if path.suffix.lower() == ".json":
        path = path.parent
    elif path.suffix.lower() == ".zip":
        path = path.with_suffix("")
    return path.name


def _row(row: Any) -> InstalledPlugin:
    return InstalledPlugin(
        name=row["name"],
        display_name=row["display_name"],
        version=row["version"],
        description=row["description"],
        source=row["source"],
        skills=json.loads(row["skills"]),
        servers=[PluginServer(**s) for s in json.loads(row["servers"])],
        connector_ids=json.loads(row["connectors"]),
        skipped=json.loads(row["skipped"]),
    )


def listing(ctx: Context) -> PluginList:
    rows = ctx.bus.db.fetch_all("SELECT * FROM plugin_installs ORDER BY created")
    return PluginList(plugins=[_row(row) for row in rows])


def propose(ctx: Context, source: str, by: str) -> InstalledPlugin:
    """Reads a plugin and proposes each of its skills for the person to review. Nothing is used
    until they approve each one; its servers wait until they're added."""
    return propose_files(ctx, fetch(source), source, by)


def propose_files(ctx: Context, files: dict[str, str], source: str, by: str) -> InstalledPlugin:
    """As propose, for files already fetched."""
    manifest, found_skills, servers, skipped = read(files, _name_of(source))
    name = str(manifest["name"])
    if ctx.bus.db.fetch_all("SELECT 1 FROM plugin_installs WHERE name = ?", (name,)):
        raise CommandError(
            "plugin.exists", f"The plugin {name} is already installed. Remove it first.", 409
        )
    proposals = []
    for skill_files in found_skills.values():
        proposals.append(skills.propose(ctx, skill_files, f"{source} (plugin {name})", by).id)
    skill_names = [skills.parse(f, "yours").name for f in found_skills.values()]
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO plugin_installs (name, display_name, version, description, source, skills,"
            " proposals, servers, skipped, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                str(manifest.get("displayName") or name),
                str(manifest.get("version", "")),
                str(manifest.get("description", "")),
                source.strip(),
                json.dumps(skill_names),
                json.dumps(proposals),
                json.dumps([s.model_dump() for s in servers]),
                json.dumps(skipped),
                _now(),
            ),
        )
        work.emit("plugins.changed", {"name": name}, source="agent", trace_id=ctx.trace_id)
    return _row(ctx.bus.db.fetch_all("SELECT * FROM plugin_installs WHERE name = ?", (name,))[0])


def _connector_ids(ctx: Context) -> set[str]:
    found = cast(Connectors, connectors.list_connectors(GetConnectors(), ctx))
    return {connector.id for connector in found.connectors}


def switch_on(ctx: Context, name: str) -> tuple[list[str], list[str]]:
    """Approves the plugin's waiting skills that raised no warnings, for when the person asked
    for it themselves. Returns the skills now on, and those still waiting for their review."""
    rows = ctx.bus.db.fetch_all("SELECT proposals FROM plugin_installs WHERE name = ?", (name,))
    on, waiting = [], []
    for identifier in json.loads(rows[0]["proposals"]) if rows else []:
        found = skills.proposal(ctx.bus.db, identifier)
        if found.status != "waiting":
            continue
        if found.flags:
            waiting.append(found.name)
        else:
            skills.decide(ctx, identifier, True)
            on.append(found.name)
    return on, waiting


def add_servers(ctx: Context, name: str, values: dict[str, str]) -> InstalledPlugin:
    """Adds the plugin's remote servers as connectors, with the secrets they ask for. Each one's
    tools are listed and checked as any connector's are."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM plugin_installs WHERE name = ?", (name,))
    if not rows:
        raise CommandError("plugin.not_found", f"No plugin called {name} is installed.", 404)
    plugin = _row(rows[0])
    missing = sorted({key for s in plugin.servers for key in s.needs if not values.get(key)})
    if missing:
        raise CommandError(
            "plugin.needs", f"Its servers need {', '.join(missing)}. Ask the person for them.", 422
        )
    added = list(plugin.connector_ids)
    for server in plugin.servers:
        before = _connector_ids(ctx)
        connectors.add_connector(connector_for(server, values), ctx)
        after = _connector_ids(ctx)
        added += sorted(after - before)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE plugin_installs SET connectors = ? WHERE name = ?", (json.dumps(added), name)
        )
        work.emit("plugins.changed", {"name": name}, source="agent", trace_id=ctx.trace_id)
    return _row(ctx.bus.db.fetch_all("SELECT * FROM plugin_installs WHERE name = ?", (name,))[0])


def remove(ctx: Context, name: str) -> PluginList:
    """Takes out everything it brought: its skills, waiting or approved, and its connectors."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM plugin_installs WHERE name = ?", (name,))
    if not rows:
        raise CommandError("plugin.not_found", f"No plugin called {name} is installed.", 404)
    plugin = _row(rows[0])
    for proposal in json.loads(rows[0]["proposals"]):
        found = ctx.bus.db.fetch_all("SELECT status FROM skill_proposals WHERE id = ?", (proposal,))
        if found and found[0]["status"] == "waiting":
            skills.decide(ctx, proposal, False)
    installed = skills.all_skills(ctx)
    for skill in plugin.skills:
        if skill in installed and installed[skill].origin == "yours":
            skills.remove(ctx, skill)
    for connector in plugin.connector_ids:
        try:
            connectors.remove_connector(ConnectorAction(id=connector), ctx)
        except CommandError:
            continue
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM plugin_installs WHERE name = ?", (name,))
        work.emit("plugins.changed", {"name": name}, source="agent", trace_id=ctx.trace_id)
    return listing(ctx)


# The person's own plugins, as folders in Home they can open, change and share.
OWN_FOLDER = "plugins"


def create(
    ctx: Context,
    name: str,
    description: str,
    new_skills: list[dict[str, str]],
    settings: str | None,
) -> tuple[Path, dict[str, str]]:
    """Writes a plugin folder in the person's Home from what they described: its skills and its
    MCP settings. A key given for a server is never written: its header becomes a placeholder and
    the value comes back to be kept as a secret when the servers are added."""
    slug = _slug(name)
    if not NAME.match(slug):
        raise CommandError("plugin.invalid", "Give the plugin a name.", 422)
    folder = ctx.config.home / OWN_FOLDER / slug
    if folder.exists():
        raise CommandError(
            "plugin.exists",
            f"You already have a plugin folder called {slug}. Pick another name.",
            409,
        )
    files: dict[str, str] = {
        "plugin.json": json.dumps(
            {
                "name": slug,
                "displayName": name.strip(),
                "version": "1.0.0",
                "description": description.strip(),
            },
            indent=2,
        )
        + "\n"
    }
    for skill in new_skills:
        skill_name = _slug(skill.get("name", ""))
        body = skill.get("instructions", "").strip()
        about = " ".join(skill.get("description", "").split())
        if not body or not about:
            raise CommandError(
                "plugin.skill", f"The skill {skill_name} needs a description and instructions.", 422
            )
        files[f"skills/{skill_name}/SKILL.md"] = (
            f"---\nname: {skill_name}\ndescription: {json.dumps(about)}\n---\n{body}\n"
        )
    values: dict[str, str] = {}
    if settings:
        servers: dict[str, Any] = {}
        for server_name, raw in servers_in(settings).items():
            if not isinstance(raw, dict):
                continue
            clean = dict(raw)
            found_headers = clean.get("headers")
            given: dict[str, Any] = found_headers if isinstance(found_headers, dict) else {}
            kept: dict[str, str] = {}
            for header, value in given.items():
                text = str(value).strip()
                if SETTING.match(text):
                    kept[header] = text
                    continue
                key = re.sub(r"[^A-Z0-9]+", "_", f"{server_name}_{header}".upper()).strip("_")
                kept[header] = f"${{user_config.{key}}}"
                values[key] = text
            clean["headers"] = kept
            servers[str(server_name)] = clean
        files[".mcp.json"] = json.dumps({"mcpServers": servers}, indent=2) + "\n"
    if len(files) == 1:
        raise CommandError("plugin.empty", "A plugin needs at least one skill or one server.", 422)
    for path, text in files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, "utf-8")
    return folder, values


def export(ctx: Context, name: str) -> Path:
    """The person's own plugin as a zip in Home's exports, to share."""
    folder = ctx.config.home / OWN_FOLDER / _slug(name)
    if not folder.is_dir():
        raise CommandError("plugin.not_found", f"You have no plugin folder called {name}.", 404)
    out = ctx.config.home / "exports" / f"{folder.name}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, f"{folder.name}/{path.relative_to(folder).as_posix()}")
    return out


def one_step(
    ctx: Context, found: InstalledPlugin, values: dict[str, str] | None = None
) -> InstallResult:
    """A plugin the person asked for themselves: skills with no warnings on, servers that need
    nothing more added (with the values given for them)."""
    given = values or {}
    on, waiting = switch_on(ctx, found.name)
    needs = sorted({k for s in found.servers for k in s.needs if not given.get(k)})
    servers: list[str] = []
    if found.servers and not needs:
        try:
            add_servers(ctx, found.name, given)
            servers = [s.name for s in found.servers]
        except CommandError as error:
            waiting.append(f"its servers ({error.message})")
    return InstallResult(
        kind="plugin",
        name=found.name,
        on=on,
        waiting=waiting,
        servers=servers,
        needs=needs,
        skipped=found.skipped,
    )


def _servers_from_settings(ctx: Context, text: str) -> InstallResult:
    found, skipped, added = [], [], []
    for server_name, raw in servers_in(text).items():
        server, why = standard_server(str(server_name), raw, secrets_allowed=True)
        if server is not None:
            found.append(server)
        if why:
            skipped.append(why)
    needs = sorted({key for s in found for key in s.needs})
    if needs:
        return InstallResult(
            kind="servers", name=", ".join(s.name for s in found), needs=needs, skipped=skipped
        )
    for server in found:
        connectors.add_connector(connector_for(server, {}), ctx)
        added.append(server.name)
    if not found:
        raise CommandError(
            "mcp.settings", "There's no server in those settings that can be used here.", 422
        )
    return InstallResult(kind="servers", name=", ".join(added), servers=added, skipped=skipped)


def _looks_like_one_skill(files: dict[str, str]) -> bool:
    return (
        skills.ENTRY in files
        and not any(path in files for path in (*MANIFESTS, *MCP_FILES))
        and not any(PurePosixPath(p).parts[:1] == ("skills",) for p in files)
    )


def install(ctx: Context, source: str, by: str) -> InstallResult:
    """What the person gave, worked out and installed in one step: pasted MCP settings become
    servers, a single skill becomes a skill, anything else is read as a plugin."""
    text = source.strip()
    if text.startswith("{"):
        return _servers_from_settings(ctx, text)
    if text.lower().endswith(skills.ENTRY.lower()) and "://" in text:
        files = skills.fetch(text)
    else:
        files = fetch(text)
    if _looks_like_one_skill(files):
        proposal = skills.propose(ctx, files, text, by)
        if proposal.flags:
            return InstallResult(kind="skill", name=proposal.name, waiting=[proposal.name])
        skills.decide(ctx, proposal.id, True)
        return InstallResult(kind="skill", name=proposal.name, on=[proposal.name])
    return one_step(ctx, propose_files(ctx, files, text, by))
