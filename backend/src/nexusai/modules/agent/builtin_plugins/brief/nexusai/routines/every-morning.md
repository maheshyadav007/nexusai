---
name: every-morning
description: Writes your brief on Today each morning, from what needs you.
agent: daily-prep
triggers:
- schedule:
    every: day
    at: '08:30'
nexusai:
  title: Every morning
  row:
    table: schedules
    kind: mail-brief
---
Write today's brief.
