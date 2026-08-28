# Contributing to CSSA-DA

Thanks for contributing. This document covers **process**: how to set up, branch,
commit, open pull requests, and cut releases.

| Looking for | Go to |
|---|---|
| What the project is, how to run it | [README.md](README.md) |
| Local Docker workflows | [docs/local-development.md](docs/local-development.md) |
| What to build and when | [docs/roadmap/](docs/roadmap/) |
| Why something is designed a certain way | [docs/design/](docs/design/) |

---

## Table of contents

- [Getting started](#getting-started)
- [Language](#language)
- [Branching model](#branching-model)
- [Commit messages](#commit-messages)
- [Pull requests](#pull-requests)
- [Testing](#testing)
- [Code style](#code-style)
- [Versioning and releases](#versioning-and-releases)
- [Documentation](#documentation)

---

## Getting started

```bash
uv sync                    # installs the `dev` group by default (api + pipeline + test tooling)
cp .env.example .env       # set OPENAI_API_KEY, DATABASE_URL, CHAT_API_KEY
uv run pytest tests/unit -q
```

Full setup instructions are in the [README](README.md#setup). For running the
stack in Docker (Postgres + migrations + API), see
[docs/local-development.md](docs/local-development.md).

---

## Language

**Everything on GitHub is written in English**: issue titles and bodies, pull
request titles and descriptions, and review and comment threads. Commit messages
are English too — see [Commit messages](#commit-messages).

The reason is who reads them. This repository already receives pull requests from
contributors outside the club who do not read Chinese. An issue they cannot read
is an issue they cannot pick up, and a review thread they cannot follow is one
they cannot answer. Keeping GitHub in one language is what makes the work
open to them at all.

Documents under `docs/` — roadmaps and design write-ups — stay in Chinese. They
are long-form, written for the team, and lose more in translation than they gain.
Changing that would be a separate and deliberate decision, not a side effect of
this rule.

This applies to new issues and pull requests. Existing Chinese ones are not being
rewritten.

---

## Branching model

`main` is always deployable. All changes land through a pull request; nobody
pushes directly to `main`.

### Naming

```
<category>/<short-description>/<author>
```

Examples:

```
feature/pluggable-retrieval/devin
fix/reranker-score-overflow/devin
chore/contributing-guide/devin
```

### Categories

| Prefix | Use for |
|---|---|
| `feature/` | New functionality |
| `fix/` | Bug fixes |
| `hotfix/` | Urgent production fixes |
| `chore/` | Config, dependencies, docs, refactors |
| `dev/` | Exploratory or experimental work |

> **Use only the prefixes above.** `unit-test.yml` runs on pushes to
> `main`, `feature/**`, `dev/**`, `chore/**` and `fix/**`. A branch named
> `bugfix/...` will not run unit tests on push (it still runs when you open a
> pull request).

### Keeping up to date

Rebase onto `main` rather than merging it in, so history stays linear:

```bash
git fetch origin
git rebase origin/main
# resolve conflicts, then:
git rebase --continue
git push --force-with-lease origin <your-branch>
```

Use `--force-with-lease` rather than `-f`: it refuses to overwrite work you have
not seen. **Never force-push `main`.**

---

## Commit messages

This repository follows [Conventional Commits](https://www.conventionalcommits.org/).
A consistent history lets the changelog and version bumps be generated
automatically once CI/CD is in place.

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

### Types

| Type | Meaning | Version impact |
|---|---|---|
| `feat` | New feature | MINOR |
| `fix` | Bug fix | PATCH |
| `perf` | Performance improvement | PATCH |
| `refactor` | Code change with no behaviour change | — |
| `test` | Tests only | — |
| `docs` | Documentation only | — |
| `build` | Dependencies, images, packaging | — |
| `ci` | CI configuration | — |
| `chore` | Anything else | — |

Mark breaking changes with `!` after the type, or a `BREAKING CHANGE:` footer.
Either triggers a MAJOR bump.

### Scopes

Use the module you touched: `api`, `rag`, `retriever`, `reranker`, `generator`,
`pipeline`, `storage`, `eval`, `infra`.

### Subject line

- Imperative mood: "add", not "added" or "adds"
- No trailing period
- Keep under ~72 characters

### Examples

```
feat(api): protect /chat with structured logging, security headers and rate limiting
fix(retriever): return stable doc_id instead of a per-request random UUID
build: lock dependencies with uv and split api/pipeline images
docs(roadmap): split future_plan into platform, data and rag tracks
```

```
feat(api)!: change ChatResponse.sources[].article.id semantics

BREAKING CHANGE: `id` is now a stable corpus doc_id instead of a random UUID.
Clients that persisted the old value must re-fetch.
```

---

## Pull requests

### Before opening

- [ ] Rebased onto the latest `main`
- [ ] Unit tests pass locally
- [ ] Integration tests pass if you touched the database or retrieval path
- [ ] New behaviour is covered by tests
- [ ] Breaking changes are flagged in the commit **and** the PR description
- [ ] Roadmap items you completed are marked in [docs/roadmap/](docs/roadmap/)

### CI

| Workflow | Runs on |
|---|---|
| `unit-test.yml` | PRs to `main`; pushes to `main`, `feature/**`, `dev/**`, `chore/**`, `fix/**` |
| `integration-test.yml` | PRs to `main`; pushes to `main` (requires Postgres) |
| `docker-check.yml` | PRs to `main`; pushes to `main` |

All checks must be green before merge.

### Review and merge

- At least one approving review.
- **Squash and merge** by default — one commit per PR keeps `main` readable, and
  the squashed subject becomes the changelog entry, so make it a valid
  Conventional Commit.
- Use **rebase and merge** only when the individual commits are each meaningful
  and independently valid.
- Delete the branch after merge.

---

## Testing

```bash
uv run pytest tests/unit -q                     # fast, no external services

RUN_INTEGRATION_TESTS=1 \
  DATABASE_URL=postgresql://... \
  uv run pytest tests/integration -q            # requires Postgres + pgvector
```

- `tests/unit/` must not touch the network, the database, or model downloads.
- `tests/integration/` may use a real Postgres with pgvector; mark them with
  `@pytest.mark.integration` (registered in `pytest.ini`).
- Add a regression test with every bug fix.

---

## Code style

- Follow PEP 8 and the conventions of the surrounding code.
- Type-annotate public functions. `mypy` is available in the `dev` group.
- Keep comments about **why**, not **what**.
- Docstrings on modules and non-obvious functions; single-line is fine.

> **Known gap:** no linter or formatter is enforced in CI today, and `mypy` has
> no configuration. Ready-to-apply `ruff` + `mypy` configuration, the CI job, and
> a two-step rollout plan are in
> [ROADMAP_platform.md](docs/roadmap/ROADMAP_platform.md) Phase 4.2.
>
> Note what lint will *not* buy you: every significant defect found in this
> project so far has been semantic (a broken id chain, an inconsistent metric, an
> unbounded input), and a linter catches none of those. Treat it as cheap
> insurance, not as a quality strategy — tests and clear contracts do that work.

---

## Versioning and releases

### Milestones are not version numbers

| | Answers | Lives in |
|---|---|---|
| **Milestone** (v1 "runs", v2 "useful", …) | When can we give this to whom | [docs/roadmap/ROADMAP_versions.md](docs/roadmap/ROADMAP_versions.md) |
| **Version number** (`v0.1.0`) | Which exact build is in production right now | Git tags |

They are many-to-one — a single milestone ships many times:

```
Milestone v1 "runs"
  ├── v0.1.0  first deployment
  ├── v0.1.1  refusal-behaviour fix
  └── v0.2.0  reranker swap
```

### Four version coordinates

When something breaks in production you must be able to answer, within a minute:
*which code, which image, which corpus, which models produced this?* All four are
recorded on every `chat_interactions` row (see
[ROADMAP_rag.md](docs/roadmap/ROADMAP_rag.md) Phase 4.5):

| Coordinate | Form | Notes |
|---|---|---|
| Code | Git tag `v0.1.0` | Immutable once pushed |
| Artifact | Image tag = Git SHA | Never deploy `latest` |
| API contract | `/v1/chat` | Tells the frontend which schema applies |
| Data | Corpus `sha256` | Metrics only compare within one corpus |

### Version numbers

Semantic versioning, staying on `v0.x.y` until public launch:

- `x` tracks the milestone (milestone v1 → `v0.1.*`)
- `y` is a patch
- Public launch bumps to `v1.0.0`

The format matters less than the property: **tags are immutable**. To withdraw a
release, publish a new version — never move an existing tag.

### API versioning

Once the frontend consumes `/v1/chat`, any change to the response schema is
breaking. Therefore:

- Version the path: `/v1/chat`
- For a breaking change, run `/v1` and `/v2` **side by side** so clients can
  migrate on their own schedule instead of coordinating a simultaneous release
- Announce removal of an old version ahead of time and record it in the changelog

> There are no API consumers yet, which makes this the cheapest possible moment
> to introduce the `/v1/` prefix. See
> [ROADMAP_rag.md](docs/roadmap/ROADMAP_rag.md) Phase 0.1.

### Cutting a release

```bash
# 1. main is green
# 2. Tag
git tag -a v0.1.0 -m "v0.1.0: first internal beta deployment"
git push origin v0.1.0
# 3. Build the image, tagged with the Git SHA
# 4. Run migrations before deploying (ROADMAP_platform item 11)
# 5. Run the smoke test after deploying
```

Automated changelog generation and tagging land with CI/CD
([ROADMAP_platform.md](docs/roadmap/ROADMAP_platform.md) Phase 4). Until then a
hand-maintained changelog tends to rot, so **only tagging is required**.

---

## Documentation

| Writing about | Put it in |
|---|---|
| What to build, in what order, what blocks what | `docs/roadmap/` |
| Why a design was chosen, and the trade-offs | `docs/design/` |
| How to run and operate the project | `README.md`, `docs/local-development.md` |
| How to collaborate | This file |

Roadmaps answer *what and when*; design documents answer *why and how*. Link
between them rather than duplicating content.
