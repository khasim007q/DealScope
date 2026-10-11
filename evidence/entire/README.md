# Entire evidence

Status: TODO. Proof is not yet captured.

- CLI version installed: 0.11.4 (installed via `irm https://entire.io/install.ps1 | iex`).
- Integration enabled / checkpoints created: TODO (not yet verified).

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
| Checkpoint ID(s) | TODO |
| Paired commit hash(es) | TODO |
| Session link | TODO |
| `entire status` output | TODO |
| `entire checkpoint explain` output | TODO |
| Screenshot paths | TODO (`evidence/entire/screenshots/...`) |
| entire-graph output (optional) | TODO |

## Captured 2026-10-11
- `entire status`: Enabled on branch main, agent Claude Code, checkpoints sync to origin.
- Commit `70400f8` ("Record traced proof runs, resume fix, eval results") trailer: `Entire-Checkpoint: 01M4NTHZJBFDKJ80R5FCA3CDZS`.
  Inspect with `entire checkpoint explain 01M4NTHZJBFDKJ80R5FCA3CDZS`.
- 5 checkpoint refs pushed to origin (`git ls-remote origin | grep refs/entire/checkpoints`).
- `entire doctor`: metadata branches OK, git hooks OK, Claude Code hook config OK, no stuck sessions.
- Gotcha: the `prepare-commit-msg` hook prompts "Link this commit to session context? [Y]es / [n]o / [a]lways"; from a
  non-interactive agent shell it waits forever. Answering `a` once in a terminal remembers the choice.
