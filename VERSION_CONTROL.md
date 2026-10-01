# VERSION_CONTROL.md

## Purpose

This file defines the repository's version-control doctrine for human maintainers and coding agents.

It governs Git state, branches, worktrees, staging, commits, history rewriting, integration, and final diff hygiene.

`AGENTS.md` controls agent execution. `PLAN.md` controls product and phase scope. This file controls version-control behavior.

When a task requires a Git operation, follow this file before acting.

## Core principles

1. Preserve user work.
2. Make the smallest coherent change for the active task.
3. Keep repository history explainable and reviewable.
4. Never use destructive Git operations as a shortcut.
5. Never mix unrelated work into one change.
6. Never claim a repository state that was not actually inspected.
7. Treat untracked, staged, committed, and worktree-local changes as materially different states.
8. External Git side effects require explicit user authorization.

## Mandatory pre-edit inspection

Before a non-trivial edit, inspect:

```bash
git status --short
git branch --show-current
git diff --stat
git diff
git diff --staged
```

If running inside a Git worktree, also inspect:

```bash
git worktree list
```

Use the results to determine:

- current branch or detached state;
- whether the working tree contains pre-existing changes;
- whether files are staged;
- whether unrelated untracked files exist;
- whether the current checkout is a linked worktree;
- whether the active task could overlap another change.

Do not assume a clean repository.

## Existing changes are protected

Pre-existing user changes are immutable unless the active request explicitly requires modifying them.

Do not:

- revert them;
- overwrite them;
- stage them accidentally;
- reformat them incidentally;
- fold them into an unrelated commit;
- delete them as cleanup;
- use them as permission to broaden scope.

If the requested change must touch a file with pre-existing edits, preserve those edits and make the smallest compatible modification.

When ownership of a hunk is ambiguous, prefer leaving it unchanged and report the ambiguity.

## Worktree doctrine

Codex may operate inside a linked Git worktree.

When a worktree is active:

- stay in the assigned worktree;
- do not switch to another worktree for convenience;
- do not remove, prune, relocate, or repair worktrees unless explicitly requested;
- do not modify another worktree's files;
- do not assume the main checkout is clean or available;
- do not switch branches merely to match a presumed canonical branch;
- preserve the worktree's current branch/detached state unless the user explicitly requests a branch operation.

A worktree path is an execution location, not authorization to alter repository topology.

## Branch doctrine

Do not create, rename, delete, switch, or merge branches unless the active request requires it or the user explicitly asks.

When branch creation is authorized:

- branch from the explicitly intended base;
- verify the base commit before creation;
- use a descriptive task-oriented name;
- do not silently rebase onto a different base.

Do not infer that `main`, `master`, or another branch is the correct integration base without checking repository state or user instruction.

## Staging doctrine

Staging is a state-changing operation.

Do not stage files unless:

- the user explicitly requested a commit or staging action; or
- an existing repository workflow explicitly requires staging for the active task.

When staging is authorized:

- stage only files/hunks belonging to the active task;
- prefer path-specific or hunk-specific staging over `git add .`;
- inspect `git diff --staged` before committing;
- never stage secrets, credentials, environment files, caches, test artifacts, or unrelated generated files.

Do not use staging as temporary storage for unrelated work.

## Commit doctrine

Do not create a commit unless explicitly requested by the user or required by an explicitly invoked repository workflow.

A passing phase does not automatically authorize a commit.

When a commit is authorized:

1. verify required tests/checks actually passed;
2. inspect `git status --short`;
3. inspect `git diff`;
4. stage only the intended task files;
5. inspect `git diff --staged`;
6. verify no secrets or unrelated changes are staged;
7. create one coherent commit for one coherent change;
8. inspect the resulting commit.

Prefer a concise imperative commit subject.

For PLAN phase commits, use:

```text
phase <N>: <concise outcome>
```

Examples:

```text
phase 2: add bounded MCP tool surface
phase 4: qualify stdio and streamable HTTP transports
```

For non-phase changes, use a concise repository-appropriate subject.

Do not add generated co-author trailers, automated attribution, or unrelated metadata unless the repository explicitly requires them.

## Commit boundaries

A commit should represent one reviewable logical unit.

Do not combine:

- implementation and unrelated cleanup;
- dependency churn and unrelated refactoring;
- multiple PLAN phases;
- documentation rewrites unrelated to the active behavior;
- user pre-existing changes with agent-authored changes.

When a task reveals an unrelated defect, fix it only if required for the active task. Otherwise report it separately.

## Amend, rebase, and history rewriting

Do not amend existing commits unless explicitly requested.

Do not run interactive or non-interactive rebase unless explicitly requested.

Do not rewrite published or shared history without explicit authorization.

Never use:

```bash
git reset --hard
git push --force
git push --force-with-lease
git clean -fd
git clean -fdx
```

unless the user explicitly requests the exact destructive action and its target has been verified.

Prefer additive/reversible corrections.

## Revert doctrine

Do not use `git revert`, checkout-based restoration, restore-based deletion of changes, or inverse patches merely to make tests pass.

A revert is a repository change and requires explicit intent.

If a newly introduced change must be undone during the same active task, edit only the agent-authored change necessary to restore correctness while preserving all pre-existing work.

## Generated and lock files

Do not modify generated, vendored, lock, or environment files unless the active task requires it.

For this repository:

- `uv.lock` is a tracked dependency-resolution artifact and should change only when dependency metadata or resolution legitimately changes;
- test caches, virtual environments, coverage output, temporary logs, and local capability artifacts are not source changes unless the PLAN explicitly requires them;
- do not manually edit `uv.lock` when `uv` should generate it.

Review generated-file diffs before accepting them.

## Line endings and formatting

Preserve existing line-ending conventions.

Do not normalize an entire file or repository solely because the current platform differs.

On Windows, CRLF-related Git warnings are not by themselves permission to rewrite files.

If a tooling command changes unrelated line endings or formatting:

- stop;
- preserve the intended functional edits;
- avoid committing mass normalization;
- report the issue if it cannot be cleanly separated.

## Secrets and sensitive data

Before staging or committing, inspect for:

- API keys;
- bearer tokens;
- cookies;
- private URLs containing credentials;
- `.env` content;
- local paths containing sensitive data;
- captured provider payloads that should not be retained.

Never intentionally commit credentials.

If a secret appears in the working tree, do not echo it into logs or handoff text.

## Dependency changes

A dependency change must be justified by the active task.

When dependencies change:

- update project metadata through the repository's supported toolchain;
- let `uv` update `uv.lock`;
- inspect dependency and lockfile diffs;
- do not perform unrelated upgrades;
- do not add global dependencies;
- do not adopt a lint/type/build tool merely because an optional command failed.

Dependency churn is not cleanup.

## Verification before commit or handoff

Before a commit, and before declaring an implementation phase accepted, inspect:

```bash
git status --short
git diff --check
git diff
git diff --staged
```

Also run the task-required tests/checks.

Verify:

- only expected files changed;
- no unrelated edits exist;
- no tests were weakened;
- no secrets were introduced;
- no generated junk was added;
- no accidental line-ending mass change occurred;
- the diff matches the active PLAN phase/request.

If files are untracked, remember that ordinary `git diff` will not display their contents. Inspect them directly or use an appropriate no-index/diff mechanism before claiming the final diff was reviewed.

## Push and remote operations

Do not push unless explicitly requested.

Do not:

- create or update remote branches;
- open pull requests;
- create tags;
- publish releases;
- modify remote repository settings;
- force-update refs

without explicit user authorization.

When a push is authorized:

- verify the destination remote and branch;
- verify the exact commits to be pushed;
- use a normal fast-forward push whenever possible;
- never force push unless the user explicitly requested it after the target was verified.

## Merge and integration doctrine

Do not merge branches or integrate worktrees unless explicitly requested.

Before an authorized merge:

- identify source and destination refs;
- verify both commits;
- inspect repository cleanliness;
- run required tests on the intended integration state where practical;
- do not silently resolve semantic conflicts.

Mechanical conflict resolution is acceptable only when the intended result is unambiguous and preserves both valid changes.

Material product, security, methodology, or public-contract conflicts must be reported rather than guessed through.

## Release/tag doctrine

Tags and releases are external version-control side effects.

Do not create either unless explicitly requested.

Before an authorized tag/release:

- verify the exact target commit;
- verify required release gates;
- verify version metadata;
- verify working tree expectations;
- report any unverified gate.

Never tag an unverified worktree state as release-ready.

## Failure recovery

When a Git operation fails:

- inspect the current state before retrying;
- do not escalate immediately to destructive commands;
- preserve user changes;
- use the narrowest reversible correction;
- report conflicts or repository-state ambiguity when they affect correctness.

Do not use destructive cleanup to recover from a misunderstood state.

## Control-plane usage

The Codex control plane must actively use this doctrine.

For every non-trivial task:

### Before editing

Codex must:

1. read `AGENTS.md`;
2. consult this file when Git state or version-control operations are relevant;
3. inspect current Git/worktree state;
4. identify pre-existing changes;
5. determine whether the requested task authorizes any Git side effect.

### During implementation

Codex must:

- preserve unrelated state;
- keep changes scoped to the active task/PLAN phase;
- avoid staging/committing/pushing unless authorized;
- treat worktree, branch, and staged-state changes as deliberate operations, never incidental ones.

### Before completion

Codex must:

1. inspect final status/diff;
2. distinguish tracked, untracked, and staged changes;
3. verify no unrelated or sensitive changes exist;
4. run applicable checks;
5. report any version-control operation actually performed.

## Final handoff requirements

When Git state is relevant, the final handoff must accurately state:

- files changed;
- whether files are tracked, untracked, or staged when material;
- whether a commit was created;
- commit SHA if one was actually created;
- whether anything was pushed;
- unresolved conflicts or repository-state concerns.

Never imply a commit, push, clean tree, or integrated state that was not verified.

## Default policy

If the user has not explicitly authorized a version-control side effect:

- edit files as required;
- test the work;
- inspect the diff;
- leave staging, commits, branches, tags, pushes, merges, and releases untouched.

That is the repository default.
