---
name: on-new-mail
description: Reads each new email as it arrives and records everything in it.
agent: mail
triggers:
- event:
    name: mail.needsTriage
nexusai:
  title: On new mail
  row:
    table: agent_triggers
    id: mail-received
---
Read this email and record everything in it: where it goes, what the person needs to do and by when, which matter it belongs to, and a draft if it needs a reply.
