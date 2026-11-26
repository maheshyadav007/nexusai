# Tools: fewer, clearer, and every read in parts

Status: plan, 2026-11-26, agreed in chat ("yes, go ahead"). To do 19, folding in To do 2. Built in steps, each with tests; tool names an eval or a skill uses are updated in the same step.

## Why

- 63 tools in the policy table, plus team, memory and skill tools. A weak model chooses better from fewer tools that each do one clear kind of thing. Anthropic's guidance on writing tools for agents says the same: consolidate, name clearly, return what's useful, and page long results with sensible defaults.
- Several reading tools can't read past their first part (`search_mail`, `list_mail`, `read_document`, `read_file`, `list_documents`). In a real run the agent read the same first part nine times.
- Every installed skill's description sits in every prompt (16 today), whatever the message is about.

## 1. Every read in parts

One rule for every tool that lists or reads:
- It takes a `page` (lists and searches, 1 is the first) or an `offset` (long text, in characters).
- Its answer ends with where it is and the exact next call: "Showing 21–40 of 134. search_mail with page=3 for more." or "Characters 0–20,000 of 84,000. read_document with offset=20000 for the next part."
- A sensible default size: 20 rows for lists, 20,000 characters for text, as today's cut-off.
- The same call twice in one run answers "Same as before: use page or offset to read further" instead of repeating it.
- A test walks every reading tool and checks it pages and says how.

Applies to: `search_mail`, `list_mail`, `semantic_search`, `search_documents`, `list_documents`, `read_document`, `read_file`, `list_folder`, `list_tasks`, `list_reminders`, `list_memory`, `read_database`. `read_thread` already pages (`skip_newest`) and stays as it is.

## 2. Merge overlapping tools

| Today | After | Notes |
|---|---|---|
| `propose_skill`, `propose_plugin`, `add_mcp_server`, `add_plugin_servers`, `create_plugin` | `install` (a link, a path, pasted settings, or a description to create from), `add_servers` | The kind is worked out from what's given; one-step rules as today |
| `list_plugins`, `remove_plugin`, `export_plugin` | `list_installed`, `uninstall`, `export_plugin` | `list_installed` covers plugins, servers and skills |
| `create_categories`, `update_category`, `merge_categories`, `reorder_categories`, `delete_categories` | `manage_categories` with an action per item | `list_categories` stays |
| `search_mail`, `semantic_search` | `search_mail` with `by: words | meaning` | Meaning falls back to words when the model for it is off |
| `search_documents` (and documents in `semantic_search`) | `search_documents` with `by: words | meaning` | |
| `create_schedule`, `update_schedule` | `save_routine`, taking a time, mail conditions or a check | The Routines agent can then set up every kind |
| `remove_schedules`, `run_schedule` | `remove_routines`, `run_routine` | |
| `update_memory`, `forget_memory` | `remember` with `replaces`, and `forget` | |

About 63 to about 45. Old names stay accepted for one release as aliases that answer with the new name, so a run in flight, an eval case or a person's own skill naming an old tool still works and learns the new one.

## 3. Skills found when they're needed

- No list of skills in the prompt; one line says skills exist and `find_tools` finds them.
- `find_tools` searches skills too and marks them: "Skill: brand-guidelines. Load it with load_skill."
- For each message, local search over skill descriptions (the `semantic` index, no model call) names the two or three closest in that run's prompt. Built-in skills an agent always needs (such as `working-with-the-team` for a hand-over) stay listed for that agent.
- A test: with 20 skills installed, Posty's prompt names at most three, and the right one for a test message is among them.

## Order

1. Paging (high value, no names change).
2. Skills found when needed.
3. Merges, one family at a time, each with its aliases, prompt and skill text updated together.

Each step: unit tests, the affected suites, `make check`, e2e, then merge.
