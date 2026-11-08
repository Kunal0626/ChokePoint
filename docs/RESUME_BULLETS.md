# Resume bullets

Two bullets that are fully supported by this repository, then some that are
not, marked with what would have to be measured first.

Every number below is reproducible: the command that produces it is given.

---

## Supported

> **Built ChokePoint, a Python attack-path and patch-priority analyzer** that
> models a network as a directed graph and computes both the cheapest
> attacker route (Dijkstra, Yen's k-shortest loopless paths) and the
> minimum-cost set of fixes that disconnects every route (Edmonds-Karp
> max-flow / min-cut) — four algorithms implemented by hand with **zero
> runtime dependencies**, analysing a **1,000-node, 5,000-edge network in
> under 160 ms**.

> **Verified the implementations against `networkx` as an independent oracle
> across 1,500 comparisons** on seeded random graphs, and stress-tested the
> **2,804-test suite by mutation testing** — injecting ~40 deliberate
> algorithmic defects — which exposed **two tests that passed against broken
> code** and were rewritten to discriminate.

### Where each number comes from

| Claim | Source | Reproduce with |
|---|---|---|
| under 160 ms at 1,000 nodes / 5,000 edges | 1.84 + 1.11 + 22.18 + 132.56 = 157.69 ms, median of 5 | `chokepoint bench --nodes 1000 --edges 5000 --seed 1` |
| zero runtime dependencies | `dependencies = []` in `pyproject.toml`; matplotlib is the optional `viz` extra, networkx the `dev` extra | `pip install chokepoint` then `pip list` |
| 1,500 oracle comparisons | parametrised oracle cases, plus 3 configurations inside one of them | `pytest --collect-only \| grep -cE "matches_networkx\|dense_and_sparse\|dense_graphs_agree\|super_source_matches"` |
| 2,804 tests | full suite, 4.4 s | `pytest` |
| ~40 mutations, 2 escapes | recorded in `docs/INTERVIEW_NOTES.md` Q13 | — |

The measurements are from Apple Silicon (arm64), macOS 26.6.2, CPython
3.14.6. Quote the machine if the bullet has room; drop the millisecond figure
rather than quote it without one.

### If you only have room for one line

> Built an attack-path analyzer in Python that finds the cheapest route to a
> crown-jewel asset and the minimum-cost set of fixes that cuts every route
> (hand-written Dijkstra, Yen's k-shortest paths and Edmonds-Karp min-cut),
> validated against `networkx` across 1,500 comparisons and 2,804 tests.

---

## Not supported — do not use these yet

> ~~"Reduced attack surface by N% across a production network"~~
> **needs:** a real network, a before/after measurement, and permission to
> cite it. ChokePoint has only ever run on three hand-made models and
> generated graphs.

> ~~"Faster than existing tools"~~
> **needs:** a like-for-like benchmark against `networkx` max-flow on
> identical graphs. networkx is used in the suite as a *correctness* oracle
> only; no timing comparison has been made, and the honest prior is that its
> flow implementations are faster than this one.

> ~~"Used by N engineers / adopted by a team"~~
> **needs:** actual users. There are none.

> ~~"Handles networks of N thousand nodes"~~ for N > 2
> **needs:** measurements above 2,000 nodes. The published sweep stops there.
> Nothing suggests it breaks, but nothing demonstrates it either.

> ~~"Supports Python 3.11+"~~
> **needs:** running the suite on 3.11. Every file has been checked to
> *parse* under 3.11, which is a syntax claim, not a support claim.

---

## A note on how to talk about it

The strongest thing about this project in an interview is not the algorithms
— plenty of people have implemented Dijkstra. It is the two places where
careful checking contradicted me:

* A test asserting my max-flow was Edmonds-Karp rather than Ford-Fulkerson
  turned out to prove nothing; I measured that the textbook pathological
  graph does not discriminate, and replaced the test with one that checks the
  lemma the complexity bound actually rests on.
* A renderer that passed every test still drew two wrong pictures, both found
  by looking at the output rather than by the suite.

Both are in `docs/INTERVIEW_NOTES.md` (Q12 and Q14). They are better material
than any bullet, because they are about engineering judgement rather than
recall.
