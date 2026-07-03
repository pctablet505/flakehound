---
name: Rule proposal
about: Propose a new flaky-pattern rule (a flaky bug you actually hit is the best kind)
title: "[rule] "
labels: rule-proposal
assignees: ""
---

**Flaky pattern**

What code shape causes flakiness? Describe it in one or two sentences.

**Minimal example**

```python
def test_example():
    ...
```

**Why is it flaky**

What's the mechanism — order dependence, timing, unmocked I/O, tolerance too
tight, GPU nondeterminism, something else? Link a postmortem/incident if you
have one; real evidence beats a plausible-sounding theory.

**Suggested fix**

What should the `fix_suggestion` text tell the user to do instead?

**Proposed confidence tier**

- [ ] HIGH — a static match is near-certain flaky-prone, safe to block a commit on
- [ ] MEDIUM — a real heuristic, plausible false positives exist
- [ ] ADVISORY — needs runtime evidence to confirm, should never block

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the confidence-tier honesty
policy and the 30-minute rule-writing walkthrough — happy to pair on the PR if
you'd rather propose than implement.
