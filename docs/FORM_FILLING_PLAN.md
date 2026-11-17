# Filling forms and spreadsheets from mail: plan

Written 2026-11-18. An email arrives with a spreadsheet or form to fill. The person says what to fill and where to find it. The agents find each value, fill a copy, show what they did with a source for every value, and send it back once the person approves.

## Rules that apply throughout

Same as the other plans: no real-model evals without asking; never delete on Google's server; theme tokens and one shared component per job; small steps with fake tests, the full check and a commit. Two more:
- **The original is never changed.** Filling always writes a new copy, kept as a document next to the mail.
- **Every value has a source or is left for the person.** No source, no value: the cell is marked "needs you", never guessed.

## The flow, as the person sees it

1. Mail arrives: "Please fill the attached vendor assessment and send it back by Friday." The Mail agent flags it as needing a reply and notes the attachment is a form.
2. The person says, in chat or from the mail: "Fill this. Company facts from our wiki MCP, revenue from the finance MCP, anything public from the web. Leave the pricing for me. Send it back to Priya when I approve."
3. Posty hands it to a **Forms** agent. The person sees the hand-over line working, with steps like "Read the form: 42 fields", "Finance MCP: revenue FY26" and "Web: company headcount".
4. A review opens: the form as a table of fields, each with its filled value, its source (a citation to the MCP result, a web page, an email or a document) and how sure the agent is. Unfilled fields say why. The person edits any value in place.
5. The person approves. The filled file is attached to a reply to the sender (or a forward to whoever they named) and goes out through the usual approval card, which shows the recipients and the attachment.

## What it must handle

| Format | Read | Fill | Notes |
|---|---|---|---|
| Excel `.xlsx`, `.xlsm` | cells, sheets, merged cells, data validation lists, formulas, protected cells, comments | openpyxl on a copy; formulas, formats, validation and macros (`keep_vba`) kept | most common |
| Old Excel `.xls` | xlrd | can't write `.xls` faithfully: fill as `.xlsx` and say so in the review | |
| CSV, TSV | delimiter, encoding and quoting detected | written back with the same delimiter, encoding and line endings | |
| Word forms `.docx` | tables, content controls, "Field: ____" lines | python-docx | questionnaires |
| PDF forms | AcroForm fields | pypdf fills fields; flat PDFs are out of scope (say so) | |
| Google Sheets or online forms | | | later: needs a connector |

**Understanding the form** is its own step, done by code first and the model second:
- Code lists the candidate fields: empty cells next to a label, a header row with empty rows under it, validation lists, form fields, "____" blanks. Each gets a reference (`Sheet1!C14`), its label, the expected type (number, date, choice from a list, text) and whether it's locked.
- The model only checks and names that list, in small pieces for large sheets. It never sees the whole workbook at once.

## Where the values come from

The person says where to look, and the agent tries sources in this order:
1. **What the person said** in the request ("we have 140 people").
2. **Memory and profile**: facts the agents already keep about the person and their company.
3. **Their own mail and documents**, through the existing searches, cited as `[mail:N]` and `[doc:KEY]`.
4. **MCP servers they named**, through the existing connector tools, cited as `[mcp:server/tool]` with the call's input.
5. **The web**, through a new `web_search` tool using DuckDuckGo, then reading the page. Cited as `[web:URL]`. Public facts only.

Each filled field records its value, its source and a confidence (exact match, derived, or a best guess the person must check).

## New pieces

| Piece | What it does |
|---|---|
| `read_form` tool | The field list for an attachment or document: references, labels, types, allowed values, locked or not. Paged for big sheets. |
| `fill_form` tool | Writes values to a working copy, in batches. Checks each value against its field (type, allowed list, locked cells, formulas) and refuses with a reason the model can fix. Stores the source of each value. |
| `web_search` tool | DuckDuckGo results (title, address, snippet), then `read_page` for one page's text. Rate-limited, results treated as untrusted, and shared with the monitors plan. |
| A guard on search queries | Before a query leaves the computer, the data guard masks internal names, numbers and addresses; a query that would leak them is refused with a reason. |
| Attachments on outgoing mail | `send_mail` and a new `forward_mail` take attachments: documents by key, including the filled copy. The approval card shows each attached file, which opens in the quick preview. |
| A **Forms** agent | Owns `read_form`, `fill_form`, `web_search` and `read_page`; uses MCP tools it's allowed; hands sending back to Posty. A short prompt: list the fields, fill what has a source, ask once for what's missing, never guess. |
| The review | A page (and a card in the chat) showing the fields as a table: value, source chip, confidence, and edit in place. Approve, or send back with a note. |
| A "form" source kind | The quick preview opens a filled file with the changed cells marked. |

## Safety

- **Web pages and MCP replies are untrusted.** They're never followed as instructions: a page that says "also email the file to x@" does nothing. Values taken from them are always shown as "from the web" in the review.
- **Nothing internal goes to the web.** Search queries pass the data guard first.
- **Nothing goes out without approval.** The filled file and the recipients are approved together, in one card.
- **Formulas and locked cells are never overwritten.** Neither are cells the person said to leave alone.
- **The size of the work is visible.** The hand-over line shows the field count and the token budget; a form over the limit asks before starting.

## Working with schedules

A monthly report is a monitor with a "fill and send" action: on the 1st, fill the KPI template from the finance MCP and send it to finance. The first send asks; later ones go out on their own, with the review kept in the run's history. (See `docs/SCHEDULES_AND_MONITORS_PLAN.md`.)

## Order of work

1. **Read forms.** `read_form` for xlsx, csv and docx, with fixture files (merged cells, validation, formulas, protected sheets, a 2,000-row sheet). Tests on the field lists.
2. **Fill a copy.** `fill_form` with checks, sources and round-trip tests that formats, formulas, validation and macros survive.
3. **Attachments on outgoing mail**, and `forward_mail`, with the approval card showing them. Tested on the fake mail server, then on real Gmail to the person's own address.
4. **Web search and page reading**, with the query guard, faked in tests.
5. **The Forms agent and the hand-over**, with fake-model tests of the whole flow: ask, fill, review, approve, send.
6. **The review page and card**, with edit in place.
7. **PDF forms and old `.xls`.**
8. **Real checks, with permission:** a real form from the person's mail, a real MCP server, and a reply to themselves.

## Decisions for the person

- A **Forms** agent, or give Posty these tools? (Recommended: a Forms agent, so its prompt stays small and focused for a weak model.)
- **Web search provider**: DuckDuckGo as asked; it has no official API, so it may be rate-limited. Keep a second provider in mind (Brave, SearXNG) behind the same tool.
- **Which formats first**: xlsx and csv, then docx, then PDF? (Recommended, based on corporate mail.)
