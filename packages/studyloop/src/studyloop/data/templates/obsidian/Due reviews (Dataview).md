# Due reviews

Optional. Needs the community **Dataview** plugin — without it this page shows the
query as plain text, which is harmless.

The query lists the plan projections StudyLoop publishes, most recently updated
first. It reads only frontmatter keys StudyLoop actually writes, so it cannot
quietly go blank when a key is renamed: a test compares the keys used here against
the ones the projection emits.

```dataview
TABLE status, progress_pct AS "Progress %", target_date AS "Target", updated
FROM "Study/Plans"
WHERE studyloop.kind = "plan-projection"
SORT updated DESC
```
