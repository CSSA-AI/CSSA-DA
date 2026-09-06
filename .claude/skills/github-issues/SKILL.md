---
name: github-issues
description: Create or edit GitHub issues for the CSSA-DA repo using this team's conventions — the "现在发生了什么 / 为什么是问题 / 改法 / 完成标准" description template, the version/stream/type/length/difficulty labels, and the one-directional link back to docs/roadmap. Trigger when the user asks to put work into GitHub, create/split/rewrite issues, plan a milestone's backlog, or says things like "加个 issue", "把这个放 issue 里", "过一遍 issue", "拆一下这条". Do NOT trigger for reading issue state (just call `gh issue list` / `gh issue view` directly).
---

# Writing GitHub issues for CSSA-DA

An issue exists so that **someone who is not you can pick it up and do it**. That
is the only test that matters. Everything below serves it.

> This project tracked work in Linear until 2026-09-06 and now uses GitHub
> issues. The conventions below are the tracker-independent ones that carried
> over, plus the GitHub mapping.

## Ask before creating

**Always show the draft and get explicit approval before calling `gh issue
create`.** Show title, labels, and the full description body. Create only after
the user says yes.

If the user asks for something to be recorded, default to **writing it into
`docs/roadmap/` first** — issues come after the roadmap says what the work is.
Do not create issues as a side effect of a design discussion.

## Description template

Four sections, in this order. The first one is what makes these issues readable
— do not drop it.

```markdown
### 现在发生了什么

<The current state, concretely. Quote the actual code or config. The reader
should be able to see the problem themselves without opening the repo.>

### 为什么是问题

<Consequences, numbered when there is more than one. Say what breaks and for
whom. If it is a latent problem rather than a live one, say so plainly.>

### 改法

<What to change. Include the code where it is short enough to inline.>

### 完成标准

- [ ] <Falsifiable checks. Not "works correctly" — "同一 query 两次请求返回相同的 id".>

<Link to the roadmap section that carries the deeper reasoning.>
```

### Notes on each section

**现在发生了什么** — the highest-value part, and the one most often written badly.

Three pieces, all of them needed:

1. **Where** — name the file so the reader can go look
2. **The code** — quote it, do not paraphrase it
3. **What it means** — the code does not explain itself. Say what it causes, and
   say it as something the reader could *observe*

```markdown
`app/schemas/article.py`：

​```python
id: str = Field(default_factory=lambda: str(uuid.uuid4()))
​```

`pg_retriever.py` 构造 `Article` 时传了 text / link / source 等等，**唯独没传
`id`** —— 于是每次都走默认值，生成一个新的随机 UUID。

同一条数据，这次检索返回 `a3f2…`，下次返回 `9c81…`。
```

That last line is what makes it click. A reader who has never opened this repo
now knows exactly what is wrong. **Code without prose is not readable; prose
without code is not verifiable — you need both.**

**为什么是问题** — when a task has no current defect (e.g. adding an API version
prefix), do not force the framing. Retitle the section (`### 为什么现在要改`) and
say honestly that nothing is broken yet, this is buying an option.

**改法** — not just a diff. A patch tells someone *what to type*; they also need
to know *why this way*, or the first surprise sends them back to you. Cover:

- **What to change**, with code when it is short
- **Why this approach** — the reasoning that is not visible in the diff
- **Which alternatives were ruled out and why** — otherwise the reviewer
  re-proposes them
- **Any trap** — the thing that looks fine but breaks

From the doc_id issue: the change is one field, but the useful part was *why not
use `link` directly* (it is a long URL and other sources have no link) and *why
not `knowledge_base.id`* (SERIAL, reassigned on re-import). From the rate-limit
issue: the code is trivial, but the trap — falling back to IP when the header is
absent, or every request lands in one bucket — is the whole point.

Long designs still belong in `docs/design/`, linked.

**完成标准** — every box must be checkable by someone other than the author.
"零编造" is checkable; "拒答行为正确" is not.

## How much to include

**The issue must contain enough to do the work without opening the roadmap** —
what to change, why it matters, how you know it is done.

**The deeper argument stays in the roadmap.** Do not reproduce a full design
rationale in an issue; link to it.

When you catch yourself pasting three paragraphs of justification, that content
belongs in `docs/roadmap/` or `docs/design/` and the issue should link to it.

## Linking is one-directional

```
GitHub issue  ──links to──►  docs/roadmap section     ✅
docs/roadmap  ──links to──►  GitHub issue             ❌ never
```

The roadmap carries design and sequencing; issues carry execution state.
Back-links create a two-way sync burden that will drift. To find out whether
something is being worked on, look at the issues — not in the roadmap.

`docs/roadmap/BACKLOG.md` is the one exception: it is the import list and is
explicitly frozen after that.

## Labels

GitHub has no label *groups*, so the axes are encoded as prefixes. Exactly one
label from each axis.

| Axis | Labels | Answers |
|---|---|---|
| Version | `v1` / `v2` / `v3` / `v4` | 属于哪个版本 |
| Stream | `stream:platform` / `stream:rag` / `stream:data` / `stream:frontend` / `stream:uiux` | 属于哪条线 |
| Type | `type:feature` / `type:improvement` / `type:bug` | 改动的性质 |
| Length | `length:<1w` / `length:1w` / `length:2w` / `length:3w` | 占多少排期 → 在哪次会上讲 |
| Difficulty | `difficulty:easy` / `difficulty:moderate` / `difficulty:hard` | 入门门槛 |
| Priority | `priority:urgent` / `priority:high` / `priority:medium` / `priority:low` | 多急 |
| Availability | `blocked` (present or absent) | 现在能不能干 |

**Version answers "which version does this deliver", not "can I work on it now".**
Work that ships in v3 but should start today gets `v3` and *no* `blocked` label —
those are different axes.

**Stream** is *whoever will pick it up*, which for cross-repo work means where
the code lives. Anything in the `myCSSA` repo is `stream:frontend`, even when
CSSA-DA owns the contract.

**Length** decides which meeting it is presented at:

- `length:<1w` — **doesn't need a slot at all**: shallow logic, small change, you
  fit it in alongside something else. Adding a `/v1` path prefix is the
  reference case.
- `length:1w` — needs a slot; reports results at the next meeting
- `length:2w` / `length:3w` — presents the design at the first meeting, results
  at the second

A small diff is *not* automatically `length:<1w`. A two-line change that sets a
convention others must follow, alters a public contract, or requires telling
another team is at least `length:1w` — the typing is not the work.

**Difficulty is barrier to entry, not effort.** Two equally time-consuming tasks
can be easy and hard.

- `difficulty:easy` — follow the issue, no need to understand the wider system
- `difficulty:moderate` — one or two design judgements, or the change reaches
  elsewhere, or it needs cross-team coordination
- `difficulty:hard` — you must understand a whole area before you can start

**Priority**:

- `priority:urgent` — v1 必须且有硬截止（契约变更 / 账单风险）
- `priority:high` — v1 必须
- `priority:medium` — 不在 v1 但现在做有回报、无阻塞
- `priority:low` — 无阻塞，可以等

## Blocked work

GitHub has no `Todo` column and no native blocked-by relation, so both are
carried by the `blocked` label plus a line in the body:

```markdown
> ⛔ Blocked by #87 — 需要先有语句超时，否则探针会挂住
```

GitHub renders that as a cross-reference on both issues, which is as close to a
native relation as this gets. **Never leave the blocker implicit in prose.**

The rule that mattered in Linear still holds: **the default view must always
equal "work someone can pick up right now"** — twelve people self-select from
it. So filter `blocked` out of the board people browse:

```
gh issue list --search "-label:blocked"
```

## Splitting

Do not bundle work because it shares a deadline. Split when the pieces differ in
**type, risk, or shippability**:

> Three changes all had to land before the frontend integrated. Bundling them
> meant a two-line security fix waited on a one-day refactor. The shared deadline
> justified the *ordering*, not one work item — it belongs in the priority label
> and a note, not in the scope.

Signals to split:

- Different Conventional Commit types (`fix` vs `feat!`) — the changelog needs
  them separate
- One piece is independently shippable today
- Different rollback granularity
- "Done 2 of 3" would be a meaningful state

## Referencing issues from git

GitHub links a PR to an issue through the **PR body**, not the branch name, so
the branch keeps this repo's convention with no issue id in it:

```
fix/stable-doc-id/devin          ✅ triggers CI
angqimeng/return-a-stable-...    ❌ CI does not run on push (branch glob)
```

PR description carries the magic word: `Fixes #74` — that closes the issue on
merge. Squash merges already append `(#74)` to the commit subject, so **do not
put the issue number in the commit subject yourself**.

See [CONTRIBUTING.md](../../../CONTRIBUTING.md).

## Language

Descriptions in Chinese, titles in English. Match the surrounding repo: roadmaps
and design docs are Chinese, code, commits and anything on GitHub are English.

Pass long bodies to `gh issue create --body-file` (a heredoc or a temp file),
never as an inline `--body` with escape sequences.
