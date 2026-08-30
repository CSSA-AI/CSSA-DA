---
name: linear-issues
description: Create or edit Linear issues for the CSSA-DA project using this team's conventions — the "现在发生了什么 / 为什么是问题 / 改法 / 完成标准" description template, the version-based projects, the Stream/Type/Length/Difficulties label groups, and the one-directional link back to docs/roadmap. Trigger when the user asks to put work into Linear, create/split/rewrite issues, plan a milestone's backlog, or says things like "加个 issue", "把这个放 Linear 里", "过一遍 issue", "拆一下这条". Do NOT trigger for reading Linear state (just call the MCP tools directly).
---

# Writing Linear issues for CSSA-DA

An issue exists so that **someone who is not you can pick it up and do it**. That
is the only test that matters. Everything below serves it.

## Ask before creating

**Always show the draft and get explicit approval before calling `save_issue`.**
Show title, project, priority, labels, estimate, and the full description body.
Create only after the user says yes.

If the user asks for something to be recorded, default to **writing it into
`docs/roadmap/` first** — Linear issues come after the roadmap says what the work
is. Do not create issues as a side effect of a design discussion.

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
Linear issue  ──links to──►  docs/roadmap section     ✅
docs/roadmap  ──links to──►  Linear issue             ❌ never
```

The roadmap carries design and sequencing; Linear carries execution state.
Back-links create a two-way sync burden that will drift. To find out whether
something is being worked on, look in Linear — not in the roadmap.

`docs/roadmap/BACKLOG.md` is the one exception: it was the initial import list
and is explicitly frozen after that.

## Workspace conventions

Team: `cssa-ai`. Repo links use
`https://github.com/CSSA-AI/CSSA-DA/blob/main/...`.

### Projects = versions

| Project | Meaning |
|---|---|
| `v1 - runnable` | 链路验证 + 开始积累真实 query |
| `v2 - usable` | 知识库第一次真的有内容 |
| `v3 - trustworthy` | 有尺子，选型完成 |
| `v4 - alive` | 运营化，飞轮闭合 |

**Project answers "which version does this deliver", not "can I work on it now".**
Work that ships in v3 but should start today goes in `v3` with status `Todo` —
those are different axes.

### Three orthogonal axes

| Axis | Field | Answers |
|---|---|---|
| Version | Project | 属于哪个版本 |
| Track | Label group **Stream** | 属于哪条线 |
| Availability | Status | 现在能不能干 |

### Label groups

- **Stream** — `Platform` / `RAG` / `Data` / `Frontend` / `UIUX`. Exactly one:
  **whoever will pick it up**, which for cross-repo work means where the code
  lives. Anything in the `myCSSA` repo is `Frontend`, even when CSSA-DA owns the
  contract.
- **Type** — `Feature` / `Improvement` / `Bug`. Exactly one.
- **Length** — how much of the schedule it consumes, which decides **which
  meeting it is presented at**.
  - `Less-than-one-week` — **doesn't need a slot at all**: shallow logic, small
    change, you fit it in alongside something else. Adding a `/v1` path prefix
    is the reference case.
  - `One-week` — needs a slot; reports results at the next meeting
  - `Two-weeks` / `Three-weeks` — presents the design at the first meeting,
    results at the second
  - A small diff is *not* automatically `Less-than-one-week`. A two-line change
    that sets a convention others must follow, alters a public contract, or
    requires telling another team is at least `One-week` — the typing is not the
    work.
- **Difficulties** — `Easy` / `Moderate` / `Hard`. **Barrier to entry, not
  effort.** Two equally time-consuming tasks can be Easy and Hard.
  - `Easy` — follow the issue, no need to understand the wider system
  - `Moderate` — one or two design judgements, or the change reaches elsewhere,
    or it needs cross-team coordination
  - `Hard` — you must understand a whole area before you can start

`Length` and `Estimate` are not redundant: estimate is effort in points, Length
is the coarse bucket used for meeting planning.

### Priority

`1` Urgent — v1 必须且有硬截止（契约变更 / 账单风险）
`2` High — v1 必须
`3` Medium — 不在 v1 但现在做有回报、无阻塞
`4` Low — 无阻塞，可以等

### Status

Blocked work goes in **`Blocked`**, never `Todo`. `Todo` must always equal "work
someone can pick up right now" — twelve people self-select from it.

Use Linear's native `blockedBy` / `blocks` relations. Never write "blocked by
X" only in the description.

## Splitting

Do not bundle work because it shares a deadline. Split when the pieces differ in
**type, risk, or shippability**:

> Three changes all had to land before the frontend integrated. Bundling them
> meant a two-line security fix waited on a one-day refactor. The shared deadline
> justified the *ordering*, not one work item — it belongs in the priority field
> and a note, not in the scope.

Signals to split:

- Different Conventional Commit types (`fix` vs `feat!`) — the changelog needs
  them separate
- One piece is independently shippable today
- Different rollback granularity
- "Done 2 of 3" would be a meaningful state

## Referencing issues from git

Put the issue ID in the branch name so Linear links it automatically, but keep
this repo's branch convention — Linear's suggested name
(`angqimeng/css-7-...`) **does not match the CI trigger globs** and would skip
unit tests on push.

```
fix/css-7-stable-doc-id/devin          ✅ links in Linear, triggers CI
angqimeng/css-7-return-a-stable...     ❌ CI does not run on push
```

Commit subject ends with the ID: `fix(retriever): return a stable doc_id (CSS-7)`
PR description carries the magic word: `Fixes CSS-7`

See [CONTRIBUTING.md](../../../CONTRIBUTING.md).

## Language

Descriptions in Chinese, titles in English. Match the surrounding repo: roadmaps
and design docs are Chinese, code and commits are English.

Send real newlines to the MCP tool, not `\n` escape sequences.
