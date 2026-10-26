# Per-person settings (set by the owner)

One file per teammate, named after what their assistant calls them (lowercase, spaces → hyphens): `paras.json`.
Their updater applies it within the hour. Keys:

```json
{
  "settings": {"greet": false, "wakeWord": true},
  "voice": {"pick": "jarvis"},
  "workflow": {"music": "lofi mix", "keepOpen": ["Claude", "Discord"]}
}
```
`settings` are kept as given (like the team's managed settings); `voice` and `workflow` keys are merged into theirs.
