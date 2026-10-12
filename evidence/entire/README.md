# Entire evidence

Status: captured (commit-linked checkpoints, pushed refs, session transcript, session timeline screenshot).

- CLI version installed: 0.11.4 (installed via `irm https://entire.io/install.ps1 | iex`).
- Integration enabled / checkpoints created: yes (`entire status`: Enabled, agent Claude Code; see below).

## Commands for the repo owner to run

```
entire login
entire enable --agent claude-code
entire status
entire checkpoint list
entire checkpoint explain <id>
```

Confirm flags against `entire --help` / `entire agent-help` for the installed version.

## Captured results

| Item | Value |
|---|---|
| Checkpoint ID(s) | `01M4NTHZJBFDKJ80R5FCA3CDZS`, `01M4NW7H2CWZJSACHHWFK2QWS9` (+ refs on origin) |
| Paired commit hash(es) | `70400f8`, `75783c2` |
| Session link | Claude Code session `9d2490e9-f406-446d-8f45-6979c161ecee`; transcript export `evidence/entire/transcript-khasim007q-DealScope-9d2490e9-f40.md` |
| `entire status` output | Enabled on branch main; agents: Claude Code; checkpoints sync to origin |
| `entire checkpoint explain` output | run `entire checkpoint explain 01M4NW7H2CWZJSACHHWFK2QWS9` (owner) |
| Screenshot paths | `evidence/entire/screenshots/entire-session-timeline.png` (Entire session view: Claude Code, Opus 5.5, 10 checkpoints, 145 file changes, +16,719 / -628, 1.7M tokens; commits 70400f8, b1e6cf4, 75783c2, be4bb90, 268b3ee, 70b7e4c each linked to the session turns that produced them) |
| entire-graph output (optional) | not produced |

## Captured 2026-10-11
- `entire status`: Enabled on branch main, agent Claude Code, checkpoints sync to origin.
- Commit `70400f8` ("Record traced proof runs, resume fix, eval results") trailer: `Entire-Checkpoint: 01M4NTHZJBFDKJ80R5FCA3CDZS`.
  Inspect with `entire checkpoint explain 01M4NTHZJBFDKJ80R5FCA3CDZS`.
- Commit `75783c2` (live browser test fixes, made by the agent after the owner chose "always") trailer:
  `Entire-Checkpoint: 01M4NW7H2CWZJSACHHWFK2QWS9`.
- 5 checkpoint refs pushed to origin (`git ls-remote origin | grep refs/entire/checkpoints`).
- `entire doctor`: metadata branches OK, git hooks OK, Claude Code hook config OK, no stuck sessions.
- Gotcha: the `prepare-commit-msg` hook prompts "Link this commit to session context? [Y]es / [n]o / [a]lways"; from a
  non-interactive agent shell it waits forever. Answering `a` once in a terminal remembers the choice.
