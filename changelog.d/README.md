# Changelog fragments

Add one Markdown fragment for each user-visible change:

```text
changelog.d/<issue-or-pr>.<type>.md
```

Supported types are `added`, `changed`, `fixed`, `removed`, `deprecated`, and `security`.
Do not edit `CHANGELOG.md` in feature PRs; the release workflow builds it with Towncrier.
