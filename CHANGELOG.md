# What's new in NexusAI

Newest first. Each entry says what changed for the person using the app, in plain words. Updated with every merge into `main`.

## 2026-11-26

**Add-ons**
- A new Add-ons page puts plugins, MCP servers and skills in one place. One box installs from a link, a folder or pasted MCP settings and says what it did. Your own plugins can be exported as a zip.
- When Posty installs a plugin, the chat shows a card with what's on, what's waiting for a look, which servers were added and what isn't used here.
- Permissions are set in nine sections, such as Reading, Mail, Sending and Your computer, with one setting each. Open a section to set a single tool. Sending always asks, and trash and deleting a document keep asking unless you change them one by one.

**Fewer approvals**
- After Posty has read an email, small changes that are easy to put back no longer ask: adding or changing tasks and reminders, filing or marking mail, saving a draft, folders, memory notes, panels and document tags. Sending, deleting, commands, files outside your Home, routines, rules and which senders the AI reads still ask.
- Tools from MCP servers you added run without asking. Set one to ask or off on the Connectors page.
- A skill, plugin or server whose link, path or address is in your own message is added in one step. A link found in an email still asks.

**Plugins, skills and MCP servers**
- Install plugins from a GitHub folder, a zip, a folder on your computer, or a single MCP settings file. Their skills and servers come in together; anything that would run a program on your computer is listed as not used.
- Posty can add an MCP server from its address alone, or from pasted settings, with headers, a token, the transport (HTTP or SSE) and a timeout. The Connectors page has the same, with "Add header" rows. Keys are kept as secrets.
- Posty can create your own plugin from what you describe, saved as a folder in your Home, and export it as a zip to share.
- A plugin's name is made lowercase with hyphens instead of being refused. A server that wants a sign-in says so.

**Routines**
- Schedules are now Routines. Your own come first; what comes with the app (the morning brief, reading new mail, the checks) is folded away under Built in.
- A routine can start on mail like this: from a sender or domain, with words in the subject, mentioning words, or mentioning you by your names.
- A routine can start on a check of a web address, telling you once when it goes down and once when it's back.
- Each routine shows its last ten runs, with Run again for one that failed.
- A Routines agent (@routines) sets up routines; Posty hands that work to it.
- Your routines run with Posty's prompt, tools and know-how.

**Reminders**
- Reminders can repeat every few minutes or hours, on chosen days, between two times, until a date: "every hour, 10:00 to 20:00, weekdays" is one reminder.

**Agents**
- The Organizer folded into Posty, which now adds and changes tasks and reminders itself.
- The Agents page shows each agent's job, what starts it, what it can't do, its skills and where it comes from.
- The triage card shows everything the Mail agent recorded, with suggestions you keep or dismiss right there.
- Each answer says which agent and plugin built it.
- Agents, skills and their prompts ship as plugins, in the same format as Claude Code's.

## 2026-11-25

- Mail signs in again by itself after a refused sign-in.
- Notifications has Clear all, with Undo.
- Calendar invites no longer clutter Documents.
- Sending mail is announced once, with its message.
