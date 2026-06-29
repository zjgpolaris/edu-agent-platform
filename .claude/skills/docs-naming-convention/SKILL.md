---
name: docs-naming-convention
description: Apply this project's docs naming convention when creating or renaming files under docs. Use minute timestamp-prefixed kebab-case filenames like 202606031530-history-character-dialogue-dev.md.
---

# Docs Naming Convention Skill

## Purpose

Use this skill whenever creating, renaming, or reviewing project documents under `docs/`.

The project convention is to prefix dated documents with a 12-digit minute timestamp, followed by a concise kebab-case topic slug.

Existing examples:

- `docs/202606031530-history-character-dialogue-dev.md`
- `docs/202606031531-history-character-dialogue-ui-ux-dev.md`

## Required Filename Format

Use this format:

```text
YYYYMMDDHHMM-topic-slug.md
```

Example:

```text
202606031530-history-character-dialogue-ui-ux-dev.md
```

Rules:

- `YYYYMMDDHHMM` must use the current local date and time to the minute.
- Use 12 digits only for the timestamp prefix.
- Use lowercase English kebab-case for the topic slug.
- Use hyphens, not spaces or underscores.
- End with `.md`.
- Keep the slug descriptive but not overly long.

## Slug Guidance

Good slugs:

```text
history-character-dialogue-dev
history-character-dialogue-ui-ux-dev
agent-api-schema-dev
frontend-streaming-response-dev
knowledge-base-build-notes
```

Avoid:

```text
历史人物对话开发文档.md
history_character_dialogue.md
HistoryCharacterDialogueDev.md
2026-06-03-1530-history-character-dialogue-dev.md
202606031530.md
new-doc.md
```

## When to Use a Timestamp

Use a timestamp prefix for:

- PRDs.
- Development documents.
- Architecture proposals.
- Feature design documents.
- Implementation plans saved under `docs/`.
- Research notes that capture a point-in-time decision.

Do not require a timestamp for stable evergreen files such as:

- `README.md`
- `CONTRIBUTING.md`
- `API.md`
- `CHANGELOG.md`

If uncertain, use the timestamp format.

## Document Title Rule

The Markdown H1 can be Chinese and human-readable, even when the filename is English kebab-case.

Example:

```markdown
# 历史人物对话界面与交互体验完善开发文档
```

## Collision Handling

If a document with the same minute timestamp and slug already exists:

1. Prefer updating the existing document if it is the same topic.
2. If it is a different topic, make the slug more specific.
3. Do not create duplicate files like `-v2`, `-new`, or `-copy` unless the user explicitly asks.

Better:

```text
202606031530-history-character-dialogue-ui-ux-dev.md
202606031531-history-character-dialogue-streaming-dev.md
```

Worse:

```text
202606031530-history-character-dialogue-dev-v2.md
202606031530-history-character-dialogue-dev-new.md
```

## Before Writing a New Doc

Before creating a new document under `docs/`:

1. List existing files in `docs/`.
2. Check whether a same-topic timestamped document already exists.
3. Choose the filename using `YYYYMMDDHHMM-topic-slug.md`.
4. Write the document to `docs/`.
5. Mention the final path to the user.

## Applying to This Project

For this project, current dated docs should follow this pattern:

```text
docs/202606031530-history-character-dialogue-dev.md
docs/202606031531-history-character-dialogue-ui-ux-dev.md
```

If creating the next development document today, use:

```text
docs/202606031530-<topic-slug>.md
```
