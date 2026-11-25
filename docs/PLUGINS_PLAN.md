# Plugins plan

One thing to install that brings skills and the outside tools they need together, with one review, one switch and one place to remove it. Researched 2026-11-25 against Claude Code plugins, Codex plugins, Agent Plugins 1.0 (VS Code and Copilot), Gemini CLI extensions and MCP Bundles. Plan only; nothing is built.

## Contents

1. [Why](#why)
2. [What the others do](#what-the-others-do)
3. [What they agree on](#what-they-agree-on)
4. [Design for NexusAI](#design-for-nexusai)
5. [Steps](#steps)
6. [Open questions](#open-questions)
7. [Sources](#sources)

## Why

Today NexusAI has two separate ways to add know-how and tools:

| Piece | Where | How it's added | Trust |
|---|---|---|---|
| Skills | `modules/agent/skills.py`, `SKILL.md` folders | `propose_skill` from a URL, file or description; the person reviews the full text | Pinned to the approved hash; a change turns it off. Instructions only, never runs, never grants a tool |
| Connectors | `modules/connectors/`, MCP servers by URL | Added on the Connectors page | Tool list hashed; new tools wait for approval. `audience` decides which agents see it |

A skill that needs an outside tool says so in `needs_tools`, but nothing installs that tool, links the two, or removes them together. The person sets up two things in two places and has to know they belong together. Every frontier tool solved this the same way in 2025–26: a **plugin**, a folder with a small manifest that bundles skills and MCP servers (and sometimes more), installed and switched as one.

## What the others do

| | Claude Code plugins | Codex plugins | Agent Plugins 1.0 (VS Code, Copilot) | Gemini CLI extensions | MCP Bundles (`.mcpb`) |
|---|---|---|---|---|---|
| Manifest | `.claude-plugin/plugin.json` (optional; only `name` required) | Root `plugin.json` (portable), `.codex-plugin/plugin.json` still read | Root `plugin.json` with the agent-plugins.org 1.0 `$schema` | `gemini-extension.json` | `manifest.json` in a zip |
| Skills | `skills/<name>/SKILL.md` | `skills/<name>/SKILL.md` | `skills/` | Context file (`GEMINI.md`), skills later | No |
| MCP servers | `.mcp.json` or inline `mcpServers` | `mcp.json`, each server with a `type` | `mcp.json` at the root | `mcpServers` in the manifest | One local server, the point of the format |
| Also | Commands, agents, hooks, LSP servers, output styles, monitors, `bin/` | App connectors (`.app.json`), hooks, icons, an onboarding skill | Vendor extras in their own folder (e.g. `com.github.copilot/`, hooks there) | Commands as TOML | — |
| Settings and secrets | `userConfig`: typed fields; `sensitive: true` goes to the OS keychain; `${user_config.KEY}` in MCP config | Per-server `auth`: `none`, `oauth`, `api_key`, `mixed`. The manifest may not hold a secret; it's asked at install or first use | Host's own | `${extensionPath}`; secrets from settings | `user_config` builds a settings form; secrets in the OS keychain; `${user_config.key}` |
| Names | Everything prefixed: `plugin:skill`, `/plugin:command` | `name` is the namespace; config key `plugin@marketplace` | Same | — | — |
| Catalog | `marketplace.json` in a repo; install `plugin@marketplace`; sources: path, GitHub, git subfolder, URL, archive, npm; pin by `ref`/`sha` | `.agents/plugins/marketplace.json`; also reads Claude's | Default catalogs plus ones you add; trust prompt for a new catalog | Install from a URL | One file, double-click |
| Trust | Validation, paths kept inside the plugin, warnings for `http://` and literal keys | Hooks are skipped until the person reviews and trusts that exact definition; plugins with hooks can't be in the public directory; MCP tool approval per tool | Advice to review publisher and contents, since hooks and MCP run code | Restart to apply | Host's sandbox |
| Updates | A set `version` pins it; otherwise follows the source | Cached per version | — | — | Reinstall |

## What they agree on

1. **A plugin is a folder, not code.** A short manifest, `skills/` and an MCP file. Everything else is optional and vendor-specific.
2. **Skills keep the open `SKILL.md` format** with progressive disclosure: only name and description up front. NexusAI already does this.
3. **One portable layout is winning.** Root `plugin.json` + `mcp.json` + `skills/` (Agent Plugins 1.0, adopted by Codex and Copilot; Claude Code reads its own folder). Readers ignore vendor folders they don't know.
4. **Secrets never live in the package.** They're declared as fields, asked at install or first use, and kept in the OS keychain.
5. **Everything is namespaced by the plugin name**, so two plugins can both have a `review` skill.
6. **What runs code is trusted separately.** Codex won't run a plugin's hooks until the person approves that exact text. Skills are text; MCP servers and hooks are the risk.

## Design for NexusAI

### What a plugin is here

A folder in the portable layout. NexusAI reads, in this order, the first manifest it finds: root `plugin.json`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`. So plugins built for Claude, Codex or Copilot install unchanged, and we use what we support.

| Part | Used? | How |
|---|---|---|
| `skills/` | Yes | Same rules as skills today: pinned, reviewed, instructions only. Named `plugin:skill` |
| `mcp.json` / `.mcp.json` / inline `mcpServers`, **remote** (`http`, `streamable-http`) | Yes | Becomes a connector owned by the plugin. Same tool-list hash and new-tool approval |
| Settings and secrets (`userConfig`, Codex `auth: api_key`) | Yes | A small form on install; secrets to `secret_store`, never the database |
| OAuth (`auth: oauth`) | Later | Needs the browser sign-in flow |
| Local MCP servers (`command`), `.mcpb` | Later, off by default | They run code on the person's machine. Needs its own approval and a sandbox decision |
| `agents/` | Later | Could become person-made agent cards; read and shown, not used, at first |
| Commands, hooks, LSP, output styles, monitors, `bin/` | No | Shown on review as "not used here" so the person knows what they aren't getting |

### Headers on MCP servers

Some MCP servers want more than a bearer token: an `X-API-Key`, a tenant or workspace id, a client id and secret pair, or a company gateway header. Today a connector takes one optional token and sends it as `Authorization: Bearer …` (`connectors/client.py`), so those servers can't be added.

- A connector gets a list of **headers**, each a name and a value. The bearer token stays as a shortcut that becomes one `Authorization` header.
- **Every header value is a secret.** Any of them may be a key, so values go to `secret_store` (one entry per connector, holding the map), never the database, never the screen after saving, and never the agent. The database keeps only the header names, so the page can show "X-API-Key, X-Tenant" with values hidden.
- **Names are checked:** letters, digits and `-` only; `Host`, `Content-Length`, `Content-Type`, `Accept`, `Connection` and `Mcp-Session-Id` can't be set, since the MCP client owns them. A limit on how many and how long.
- **Values are sent only to that server**, as given, on list and on every call. Not on redirects to another host.
- **Changing a header** is like changing the token: the server is listed again, and new tools still wait for approval.
- **From a plugin:** `headers` in a plugin's MCP config are read, and any `${user_config.KEY}` in them is asked for on install (Claude Code's `userConfig`, Codex's `api_key` with a `headerScheme`). A literal key written into a plugin's headers is refused on review, as Claude Code warns about it.
- **On screen:** the add and edit form on the Connectors page gets "Add header" rows, name and hidden value. Needs a mockup.

### One review, one switch

- Posty adds a plugin the same way it adds a skill: the person gives a URL (GitHub folder, zip, a catalog entry) and Posty calls `propose_plugin`.
- **Review card** shows: name, source and version; each skill (full text, the existing warning flags); each MCP server (address, what it asks for, its tool list once it can be reached); the settings it needs; which agents get it; and the parts not used here.
- **Approval pins the whole plugin** to one hash of its files. A change at the source turns it off until approved again, like skills today. It never updates by itself.
- **One switch** turns its skills and connectors on or off together. **Remove** deletes its skills, its connectors and its secrets.
- Safety rules already in `AGENT_HARNESS_PLAN.md` still hold: Rule of Two (S1) applies to plugin tools like any other, a skill never grants a tool, and no agent installs a plugin without the person.

### Which agents get it

A plugin is given to agents, not to everything. Default: Posty only. The person can add others on review. The `agents` list of each skill and the `audience` of each connector come from that one choice, so they can't disagree.

### Keep the prompt small (weak model)

Plugins are how tool lists grow, and a weak model gets worse with every tool it sees. Two rules:

1. **A plugin's tools come with its skill.** If a plugin has skills, its MCP tools are hidden until one of its skills is loaded in that run. A plugin with no skills shows its tools as connectors do today. (None of the frontier tools does this by default; Claude Code's tool search is the nearest. It fits our goal better than showing everything.)
2. **A limit on tools per agent.** Past the limit, installing asks which agent should drop or not get the new tools.

### Data

- New `plugins` table: id (the name), source, version, hash, enabled, agents, settings (non-secret), installed, approved.
- `skill_approvals` and `connectors` get a `plugin` column. A row with a plugin is managed by that plugin: it can't be removed or switched on its own.
- Files live in the data folder under `plugins/<name>/<version>/`, as skills live under `skills/` today.

### Catalogs (later)

Read `marketplace.json` (Claude's `.claude-plugin/` and Codex's `.agents/plugins/` paths) so a company can publish a list of approved plugins. Adding a catalog is itself approved once. Each install from it still gets the full review.

## Steps

Each step ships on its own. Plan stage now; build when told.

0. **Headers on MCP servers.** Ships on its own, before plugins: the list of headers, values in `secret_store`, the name checks, and the form (mockup first). Plugins then reuse it.
1. **Read a plugin.** Manifest reader for the three locations, skills and remote MCP servers only, with name prefixes. Tests with a Claude-layout and a portable-layout plugin in fixtures. No UI.
2. **Install and remove through Posty.** `propose_plugin`, the review card, the `plugins` table, one hash, one switch, remove that cleans up. The card needs a **mockup first**.
3. **Settings and secrets.** `userConfig` and `api_key` fields, the form in the card, values in `secret_store`, `${user_config.KEY}` in the server config.
4. **Tools come with the skill.** Hide a plugin's tools until its skill is loaded, plus the per-agent limit. Fake-model tests; a real-model check only after asking.
5. **Plugins on the Agents page.** A list with switch, version, source and what each agent got. **Mockup first.**
6. **Later:** OAuth, catalogs, `agents/` as agent cards, then local servers and `.mcpb` with their own approval.

**Done when:** installing one plugin from a GitHub URL, built for Claude Code, gives Posty its skill and its tools after one review; turning it off removes both from the next run; changing the plugin at its source turns it off until approved; and removing it leaves no skill, connector or secret behind.

## Open questions

- Should a skill or connector the person added on its own be allowed to move into a plugin later, or do they stay separate?
- Default agents: Posty only, or also the agent whose job matches?
- Local MCP servers: never, or later behind a separate "runs on this computer" approval?
- Do we publish our own shipped skills as a plugin (so others can use them), or keep them built in?

## Sources

- Claude Code: [Plugins](https://code.claude.com/docs/en/plugins), [Plugins reference](https://code.claude.com/docs/en/plugins-reference), [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces), [Announcement](https://claude.com/blog/claude-code-plugins)
- Codex: [Build plugins](https://developers.openai.com/codex/plugins/build/), [Plugins](https://developers.openai.com/codex/plugins), [Launch coverage, March 2026](https://www.siliconangle.com/2026/03/27/openai-introduces-plugins-codex-programming-assistant/)
- Agent Plugins 1.0: [VS Code agent plugins](https://code.visualstudio.com/docs/copilot/customization/agent-plugins), [Authoring reference](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference), [GitHub changelog, August 2026](https://github.blog/changelog/2026-08-12-agent-plugins-1-0-in-vs-code-copilot-cli-and-the-copilot-app), [Copilot plugin reference](https://docs.github.com/en/copilot/reference/plugin-and-marketplace-reference)
- Gemini CLI: [Extension reference](https://geminicli.com/docs/extensions/reference/), [Announcement](https://blog.google/technology/developers/gemini-cli-extensions/)
- MCP Bundles: [Desktop extensions](https://www.anthropic.com/engineering/desktop-extensions), [mcpb on GitHub](https://github.com/modelcontextprotocol/mcpb)
- Agent Skills standard: [agentskills.io](https://agentskills.io/), [Donation to the Agentic AI Foundation](https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation)
