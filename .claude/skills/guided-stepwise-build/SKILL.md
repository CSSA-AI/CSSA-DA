---
name: guided-stepwise-build
description: Implement a feature as a series of small, individually-reviewed steps while teaching the user the underlying concepts. Use when the user wants to learn as they build — signalled by phrases like "one step at a time", "explain before you code", "I want to understand / check your work at each step", "don't do it all at once", "先解释再动手", "一步一步来", or when they are building something as a learning/portfolio exercise and ask for explanations. Enforces: explain design + fundamentals before writing code, wait for explicit approval each step, and run the full test suite per step.
---

# Guided Stepwise Build

Build a feature slowly and legibly, so a learning user stays in control and
understands every change. Optimise for the user's understanding and sense of
ownership, not for finishing fast.

## Core loop (one step at a time)

For each step, in order:

1. **Propose the design first — do not touch code.** Describe what this step
   does, the approach, and the trade-offs. If the mechanism relies on a
   language/framework concept the user may not know, explain that concept from
   first principles *before* the design that uses it (see "Teaching stance").
2. **Wait for explicit approval.** The user must say go. Treat questions as
   questions, not approval. If they ask "explain X", answer and re-confirm —
   answering a question is not permission to start coding. Never batch multiple
   steps into one approval.
3. **Implement only the approved step.** Keep the diff minimal and in the style
   of the surrounding code. Do not sneak in later steps.
4. **Verify, then report honestly.** Run the full relevant test suite (not just
   the new test). State the real result — pass counts, regressions, and
   anything you could not verify (e.g. integration tests needing services you
   didn't start). If you couldn't run something, say so; don't imply you did.
5. **Offer the next step; stop.** Summarise what changed (link files/lines) and
   ask whether to continue. Let the user drive the pace.

## Teaching stance

The user is learning. When you introduce a concept:

- **Background before definition.** Lead with *why the thing exists / what
  problem it solves*, then what it is. Never drop a term cold.
- **Concrete over abstract.** Prefer a worked example, a real request/response,
  or a tiny experiment you actually ran (show its output) over prose.
- **Answer the actual question asked.** If the user asks "what is `X`", explain
  `X` specifically and plainly; re-explain differently if they say it's unclear,
  rather than repeating the same words.
- **Connect back to their goals.** Tie choices to what they care about (here: a
  portfolio-quality, production-ready, eventually-AWS-deployed project).

## Planning a multi-step feature

Before the loop, once: break the feature into the smallest steps that each
build and pass tests on their own, and record them as a durable checklist
(e.g. in the project's plan/roadmap doc) so the user can see the whole arc and
resume across sessions. Convert relative dates to absolute. Prefer reusing
mature libraries for standard needs over hand-rolling, and call that trade-off
out — it's a teachable point.

## Guardrails

- **Never write code before the current step is approved**, even if the next
  step seems obvious.
- **Never claim a step is done without running its verification**, and never
  overstate what the verification covered.
- **Detect the project's real test/run environment** rather than assuming.
  (Example from this repo: a committed `.venv/` held all deps while the system
  Python had none — always locate the actual interpreter first.)
- If the user pushes back or asks to adjust the design, revise and re-confirm
  before coding.

## Companion skill

Writing a design document is NOT part of this loop — explaining each step
(loop step 1) happens in chat, not in a file. Only when the user explicitly
asks to write or update a design doc, use the `design-details-md` skill.
