## What & why

<!-- One or two sentences. If this adds a rule, name the rule id and the cause. -->

## Checklist

- [ ] One rule per PR (or a focused, single-purpose fix)
- [ ] True-positive test **and** a false-positive guard test included
- [ ] Confidence tier matches what the rule can actually prove statically
      (see [CONTRIBUTING.md](../CONTRIBUTING.md#confidence-tier-honesty-read-this-before-picking-a-tier))
- [ ] `fix_suggestion` is concrete and actionable, not generic advice
- [ ] `ruff check src tests && ruff format --check src tests` passes
- [ ] `pyright src` passes
- [ ] `pytest -p randomly -q` passes
- [ ] `flakehound scan tests/` stays clean
- [ ] Docstring cites *why* the pattern flakes, not just *what* it matches

## Related issue

<!-- Closes #... -->
