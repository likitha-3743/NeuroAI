# Adding your own domain pack (no code)

A pack is a folder under `neuro_san/coded_tools/escalation_iq/domain_packs/<your_domain>/` with two files.
The folder name becomes the domain name. Restart the server after editing a pack (files are cached).

## 1. `history.csv`

Columns, in order:

```text
case_id,date,category,severity,stakeholder_tier,value_at_risk,description,resolution,outcome,escalated,escalated_to,hours_to_resolve,satisfaction
```

- `date` is `YYYY-MM-DD`. The latest date in the file acts as "today" for recurrence detection.
- `category` must exist in `config.json`, and `resolution` must be a key of the playbook.
- `outcome` is one of `resolved`, `escalated_resolved`, `reopened`, `failed`.
- `escalated` is `yes` or `no`; `escalated_to` is the team (blank when not escalated).
- Write descriptions in natural language: similarity search works on them. 20 to 30 rows is enough for a demo.

## 2. `config.json`

| Key | Purpose |
| --- | --- |
| `display_name`, `case_noun`, `description`, `default_team` | Labels and the fallback owner |
| `severity_levels` | Definitions shown to the classifier |
| `taxonomy.categories` | Per category: `business_area`, `team`, `regulated`, `keywords`, `guidance` |
| `priority.severity_points` | Points per severity |
| `priority.impact_rules` | Rules that add points (`label`, `points`, `when` conditions) |
| `priority.thresholds` | Points needed for P1, P2, P3 (otherwise P4) |
| `sla_hours` | Hours allowed per priority |
| `recurrence` | `window_days`, `similarity_threshold`, `systemic_threshold` |
| `scoring` | Optional overrides of the default scoring table (for example `value_points`) |
| `rules` | Escalation policy rules |
| `playbook` | Resolution options with `authority_level`, `max_value`, `categories`, `steps` |

### Rule syntax

```json
{"id": "R01", "description": "Legal threat needs Legal", "escalate_to": "Legal", "weight": 30,
 "mandatory": true, "level": "L3",
 "when": [{"field": "legal_or_media_threat", "op": "==", "value": true}]}
```

`when` conditions are AND-ed; an optional `when_any` list is OR-ed. Operators: `==`, `!=`, `>`, `>=`, `<`, `<=`,
`in`, `not_in`, `contains`. Fields you can use: `category`, `severity`, `priority`, `stakeholder_tier`,
`value_at_risk`, `hours_open`, `prior_contacts`, `regulated`, `legal_or_media_threat`, `safety_or_data_risk`,
`frustration_level`, `sla_pct`, `repeat_similar_count`.

A `mandatory` rule forces at least ESCALATE (URGENT for a P1). Other rules add `weight` points (scaled and capped).

## 3. Use it

Tell the chair which domain you mean, or add a keyword for it in the chair's domain list in
`escalation_iq.hocon` (the "AVAILABLE DOMAINS" paragraph) and in the `domain` description of `case_intake`.
Then run `python scripts/smoke_test_escalation_iq.py` after pointing a scenario at the new domain.
