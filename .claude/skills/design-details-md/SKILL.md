---
name: design-details-md
description: Create or maintain a design_details.md file — a design write-up that doubles as a beginner-friendly learning reference (big picture first, fundamentals taught in clusters with origin/motivation, trade-offs explained, low-level code mechanics left out). Trigger ONLY when the user explicitly asks to write to or edit a design document/file — e.g. "write the design doc", "put this in design_details.md", "add this to the doc", "update / reorganise the design doc", "写进设计文档 / 记录到 design_details.md / 更新文档 / 重排文档". Do NOT trigger for requests that merely want a spoken explanation ("explain this design", "解释一下 / 给小白讲讲 / 给点 background") — those are answered in chat, not by editing the doc. Companion to guided-stepwise-build (its per-step documentation step).
---

# design-details-md

Produce a design write-up that doubles as a learning reference for someone new
to the stack. The reader should be able to start from zero and come out
understanding both *what was built* and *why*, without needing to already know
the framework.

## Ordering: map before streets

Structure top-to-bottom so each concept has somewhere to hang before it appears:

1. **Background** — what this change is and why it's being made (the
   problem/need, the intended outcome).
2. **The big picture** — one diagram + plain-language walkthrough of the whole
   flow (e.g. the journey of a request through the layers), *with no jargon*.
   Point out where each later step/section fits on this picture. This section is
   the single biggest help to a beginner — never skip it.
3. **Fundamentals**, grouped into a few labelled clusters that build on each
   other (outer→inner, or foundational→derived). Give each cluster a one-line
   "what this cluster is for". Order clusters so prerequisites come first (e.g.
   "how a request reaches my code" before "how I log what happens"), and put any
   concept that *glues two clusters together* last.
4. **The steps / implementation**, each linking back to the fundamentals it
   relies on (`> Prerequisite basics: ...`).
5. **Cross-cutting sections** (ordering rules, testing strategy, what's not done
   yet).

## Teaching each fundamental

- **Origin first.** Open with *how the thing came to exist / what it solves* —
  the naive approach and why it fails — then define it. Two or three sentences
  of motivation, then the mechanics. Never introduce a term with no lead-in.
- **Show, don't just tell.** Include a concrete illustration: a real payload, a
  small dict/example, or the output of a tiny experiment. For protocol/format
  concepts, show what the data actually looks like.
- **Name the trade-off.** Where a choice was made (library vs hand-rolled,
  strict vs lenient, string vs typed config), state the alternatives and why
  this one — that reasoning is the teachable part.

## Level of detail — keep it design, not code walkthrough

- **In:** concepts, architecture, data/really-happening flow, security/attack
  scenarios, config-as-design (the meaningful parameters and chosen values),
  and *why* decisions were made.
- **Out:** line-by-line code mechanics — exact function bodies, `nonlocal`,
  indentation gotchas, precise signatures. Refer to them by name and intent
  ("uses the wrapped-`send` trick to append the header") without reproducing the
  implementation. The doc should stay valid even as the code is refactored.
- Keep illustrative code to *protocol/shape examples* and *config blocks*, not
  copies of the project's implementation.

## Mechanics

- Use clickable relative links for every file/line reference.
- Keep a table of contents with anchors when the doc grows past a few sections.
- Keep numbers real (test counts, versions) and consistent with the code as it
  actually stands right now.
- When adding a new step to an existing doc, also update the TOC, anchors, and
  any "prerequisite basics" back-references so nothing dangles.
- Put the doc where the project keeps its other docs (match existing convention,
  e.g. repo root alongside README).
