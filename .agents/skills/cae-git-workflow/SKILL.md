---
name: cae-git-workflow
description: Track CAE Agent development with scoped Git changes, GitHub issues, the CAE Agent Roadmap project, commits, and pull requests. Use when implementing or fixing SpaceClaim, Workbench, Mechanical, Fluent, Icepak, CAE UI, automation, documentation, tests, or repository maintenance in minwoorich/cae-agent, especially when the user asks to manage work with Git, issues, projects, branches, commits, or PRs.
---

# CAE Git Workflow

Keep every repository change traceable without publishing generated CAE data or unrelated user work.

## Workflow

1. Run `git status -sb`, inspect the relevant diff, current branch, remote, and default branch.
2. Separate requested changes from pre-existing work. Never stage the whole tree when scope is mixed.
3. Reuse a matching issue or create one with the goal, scope, acceptance criteria, and validation plan.
4. Add the issue to `CAE Agent Roadmap` and set its actual workflow state.
5. Use `agent/<issue-number>-<short-description>` from the default branch. Do not switch branches when unrelated local changes make that unsafe.
6. Stage explicit paths only, commit the scoped result, and run targeted tests followed by full `pytest`.
7. Push only when publication was requested. Open a draft PR by default and link `Closes #<issue>`.
8. Report issue, project item, branch, commit, PR, tests, and untouched local work.

## Guardrails

- Never commit `workspace/`, CAE solver outputs, licenses, tokens, local configuration, or absolute user paths.
- Treat `.wbpj`, `_files/`, `.scdocx`, `.aedt`, `.aedtz`, `.cas.h5`, `.dat.h5`, `.msh`, `.trn`, and Fluent cleanup files as local artifacts unless explicitly approved as fixtures.
- Add repeatable runtime debris to `.gitignore` instead of deleting user data.
- Preserve branches and commits; never use destructive reset or checkout commands.
- Do not close an issue until acceptance criteria are verified.
- Use the GitHub connector for issues and PR metadata, with `git` and `gh` for local operations and Projects gaps.

Keep product engineering work separate from physical CAE study results. Issues track software behavior; numerical assumptions and conclusions belong in result reports.
