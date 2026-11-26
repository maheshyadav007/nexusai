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

from nexusai.contracts.agent import InstalledPlugin, PluginList, PluginServer
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
REMOTE = {"http", "streamable-http", "sse"}
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
    """A plugin's text files from a GitHub folder, a zip address, or a folder on this computer."""
    text = source.strip()
    local = Path(text).expanduser()
    if text.startswith(("/", "~")) or (len(text) > 2 and text[1] == ":"):
        if not local.is_dir():
            raise CommandError("plugin.fetch", f"There's no folder at {text}.", 422)
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


def _manifest(files: dict[str, str]) -> dict[str, Any]:
    for path in MANIFESTS:
        if path in files:
            try:
                found = json.loads(files[path])
            except json.JSONDecodeError as error:
                raise CommandError("plugin.invalid", f"{path} isn't valid JSON.", 422) from error
            if not isinstance(found, dict):
                raise CommandError("plugin.invalid", f"{path} isn't a JSON object.", 422)
            return found
    raise CommandError(
        "plugin.invalid",
        "It has no plugin.json, so it isn't a plugin. A skill alone is added as a skill.",
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


def _server(name: str, raw: Any) -> tuple[PluginServer | None, str | None]:
    """A remote server, or why it isn't used here."""
    if not isinstance(raw, dict):
        return None, f"MCP server {name}: not a server description"
    kind = str(raw.get("type") or ("stdio" if raw.get("command") else "http"))
    url = str(raw.get("url") or "")
    if kind not in REMOTE or not url.startswith(("https://", "http://")):
        return None, f"MCP server {name}: it runs on this computer, so it isn't used here"
    needs: list[str] = []
    given = raw.get("headers")
    headers: dict[str, Any] = given if isinstance(given, dict) else {}
    for header, value in headers.items():
        match = SETTING.match(str(value).strip())
        if not match:
            raise CommandError(
                "plugin.secret",
                f"MCP server {name} has a value written into its {header} header. A plugin must"
                " ask for secrets instead, so it isn't installed.",
                422,
            )
        needs.append(match.group(1))
    return PluginServer(name=name, url=url, headers=dict(headers), needs=needs), None


def read(
    files: dict[str, str],
) -> tuple[dict[str, Any], dict[str, dict[str, str]], list[PluginServer], list[str]]:
    """What's in a plugin: its manifest, its skills' files, its remote servers, and what isn't used."""
    manifest = _manifest(files)
    name = str(manifest.get("name", ""))
    if not NAME.match(name):
        raise CommandError("plugin.invalid", f"Its name, {name!r}, isn't a plugin name.", 422)
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


def _row(row: Any) -> InstalledPlugin:
    return InstalledPlugin(
        name=row["name"],
        display_name=row["display_name"],
        version=row["version"],
        description=row["description"],
        source=row["source"],
        skills=json.loads(row["skills"]),
        servers=[PluginServer(**s) for s in json.loads(row["servers"])],
        connectors=json.loads(row["connectors"]),
        skipped=json.loads(row["skipped"]),
    )


def listing(ctx: Context) -> PluginList:
    rows = ctx.bus.db.fetch_all("SELECT * FROM plugin_installs ORDER BY created")
    return PluginList(plugins=[_row(row) for row in rows])


def propose(ctx: Context, source: str, by: str) -> InstalledPlugin:
    """Reads a plugin and proposes each of its skills for the person to review. Nothing is used
    until they approve each one; its servers wait until they're added."""
    files = fetch(source)
    manifest, found_skills, servers, skipped = read(files)
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
    added = list(plugin.connectors)
    for server in plugin.servers:
        headers = {}
        for header, value in server.headers.items():
            match = SETTING.match(str(value).strip())
            if match:
                headers[header] = values[match.group(1)]
        before = _connector_ids(ctx)
        connectors.add_connector(
            AddConnector(
                name=server.name[:60], url=server.url, audience="internal", headers=headers
            ),
            ctx,
        )
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
    for connector in plugin.connectors:
        try:
            connectors.remove_connector(ConnectorAction(id=connector), ctx)
        except CommandError:
            continue
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM plugin_installs WHERE name = ?", (name,))
        work.emit("plugins.changed", {"name": name}, source="agent", trace_id=ctx.trace_id)
    return listing(ctx)
