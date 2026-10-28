# flakehound

flakehound reads your pytest files and points at code that can make a test pass on one run and fail on the next,
without running the tests. It is not on PyPI yet, so install it from this repository:

```bash
pip install git+https://github.com/pctablet505/flakehound
flakehound scan tests/
```

## A flaky test, the finding, the fix

This test passed under 10 of 50 Python hash seeds and failed under the other 40. Python picks a hash seed at random
for each run, and the seed decides the order of a set of strings.

How it was counted: the assert's expression, run once per seed with `PYTHONHASHSEED=1` to `50` and `python3 -c`.

```python
def test_supported_devices():
    devices = ["gpu", "cpu", "tpu", "cpu"]
    assert list(set(devices)) == ["cpu", "gpu", "tpu"]
```

`flakehound scan tests/` printed this (flakehound 0.1.0, run on 21 October 2026; long lines wrapped to fit a phone):

```text
tests/test_devices.py:3:11: [G2/high]
`list(set(...))` materializes a set
into a list; set iteration order is
not guaranteed to be stable across
runs
    fix: sort both sides before
    comparing (`sorted(x) ==
    sorted(y)`), or compare as
    sets/dicts directly (`set(x) ==
    set(y)`) if order was never the
    point

flakehound: 1 finding(s) in 1 test
file(s)
```

With `assert sorted(set(devices)) == ["cpu", "gpu", "tpu"]` the scan reports 0 findings, and the test passes under all
50 seeds.

## What it checks

G2, the rule above, is one of 17. The other 16 cover global random seeds, sleeps, the wall clock, shared fixtures,
network calls and more, and 5 of them are for ML tests (JAX, PyTorch, NumPy), such as a tolerance tighter than float
noise. [Every rule, with a bad and a good example →](docs/rules.md)

## Use it

```bash
flakehound scan tests/      # static scan: runs no tests
pytest --flakehound         # the same rules, as part of a pytest run
```

The scan exits with 1 when a finding is at or above the level set by `fail_on`, so it can stop a CI job. Settings live in
`pyproject.toml`:

```toml
[tool.flakehound]
fail_on = "high"      # level that fails: high, medium, advisory, never
disable = ["G3"]      # rule ids to skip
exclude = ["tests/legacy/*"]
ml_rules = true       # the 5 ML rules
```

## Limits

- **It knows patterns, not every bug.** The same set-order bug with the set in a variable (`devices = {...}`, then
  `list(devices) == [...]`) got 0 findings, though that test passed under only 9 of 50 seeds.
- **Not measured: how often it is right on real projects.** No accuracy figure is published yet; benchmarks on public
  flaky-test datasets are planned ([docs/benchmarks.md](docs/benchmarks.md)).
- **Not history-based yet.** Scoring tests from their past runs is planned for v0.2.
- **Alpha, version 0.1.0.** The pre-commit hook needs a release tag, and none exists yet.

## Where next

- [docs/rules.md](docs/rules.md): the 17 rules, each with a bad and a good example.
- [docs/details.md](docs/details.md): the longer overview that used to be here, with the pre-commit setup, the roadmap
  and the studies on how common flaky tests are.
- [CONTRIBUTING.md](CONTRIBUTING.md): a new rule is one module, a test it must catch and a test it must not.

Apache-2.0, see [LICENSE](LICENSE).

---

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/mark-dark.svg"><img src="assets/mark-light.svg" width="16" height="16" alt=""></picture>
<sub>**Big models, small places, real numbers** · Built by [pctablet505](https://github.com/pctablet505).</sub>
