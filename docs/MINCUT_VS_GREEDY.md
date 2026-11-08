# Why the minimum fix set and the single-fix ranking disagree

Every number here is produced by a script in the repository:

```bash
.venv/bin/python scripts/explain_ranking.py
```

---

## The short version

The report's section 2 and section 3 answer **different questions**, so they
can and do recommend different work.

| | Section 2: minimum fix set | Section 3: single-fix ranking |
|---|---|---|
| Question | What is the cheapest set of fixes that stops the attacker **completely**? | Which **one** fix slows the attacker down the most? |
| Objective | Minimise total cost subject to full disconnection | Maximise the rise in the cheapest attack cost |
| Output | A set, jointly optimal | An ordering of individuals |
| Guarantees | Provably cheapest adequate set | Nothing about sets at all |

A fix can be essential to the cheapest adequate set and yet achieve *nothing*
on its own. A fix can be the single most effective thing you could do and yet
belong to no minimum cut. Both happen in one small example below.

## The example that shows both at once

A jump host that both fast routes pass through, plus a slow contractor
bypass.

```
                     ┌──> App server ───┐
                     │    (patch: 1)    │  (rotate: 1)
   Internet ──> Jump host               ├──> Database
   (harden: 20) │   │                   │
                │   └──> Build server ──┘
                │        (lock CI: 1)     (scope CI: 1)
                │
                └──> Contractor VPN ──> Database
                     (MFA: 1)            (segment: 1)
```

```
baseline cheapest attack cost: 3
top-3 paths:
  #1  difficulty   3   Internet -> Jump host -> App server -> Database
  #2  difficulty   3   Internet -> Jump host -> Build server -> Database
  #3  difficulty  18   Internet -> Contractor VPN -> Database

minimum fix set (total cost 3):
  cost   1   Lock down CI agent
  cost   1   MFA on contractor VPN
  cost   1   Patch app server

single-fix ranking:
  fix                        cost  after  raises  paths  in cut?
  --------------------------------------------------------------
  Harden jump host             20     18     +15   2/3  no
  Lock down CI agent            1      3      +0   1/3  yes
  MFA on contractor VPN         1      3      +0   1/3  yes
  Patch app server              1      3      +0   1/3  yes
  Rotate app DB password        1      3      +0   1/3  no
  Scope CI credentials          1      3      +0   1/3  no
  Segment contractor VLAN       1      3      +0   1/3  no

best single fix by effect : 'Harden jump host' (cost 20, raises by +15)
is it in the minimum cut? : NO
cut members with +0 effect: 3 of 3
```

Read those two sections against each other:

**The best single fix is not in the cut.** Hardening the jump host raises the
attacker's cost from 3 to 18 — more than any other fix — and touches 2 of the
top 3 paths. It appears in no minimum cut, because it costs 20 and the same
routes can be severed downstream for 1 apiece.

**Every member of the cut scores +0.** Patch the app server and the attacker
simply uses the build server, still at cost 3. Each cut member looks useless
in isolation. Together, for a total of 3, they disconnect the database
entirely — which the 20-cost fix never does.

So the two sections give opposite advice, and both are right:

- *"Spend 20 and the attacker's cheapest route gets six times harder."*
- *"Spend 3 and there is no route at all."*

A tool that printed only the ranking would have you buy the first. A tool that
printed only the cut would never tell you that one change touches two thirds
of your attack surface — useful to know if the three cheap fixes are blocked
on a change-freeze. Hence both sections.

## When the ranking degenerates completely

Two identical disjoint routes:

```
minimum fix set (total cost 4):
  cost   2   Fix route A entry
  cost   2   Fix route B entry

single-fix ranking:
  fix                        cost  after  raises  paths  in cut?
  --------------------------------------------------------------
  Fix route A entry             2      2      +0   1/2  yes
  Fix route A exit              2      2      +0   1/2  no
  Fix route B entry             2      2      +0   1/2  yes
  Fix route B exit              2      2      +0   1/2  no
```

Every fix raises the cost by exactly +0, because whichever route you close the
other is equally cheap. The ranking carries no information at all here. The
min-cut still gives the right answer: close one hop on each route, total 4.

This is the general shape of the problem. **Greedy single-fix analysis is
blind to redundancy**, and redundancy is exactly what a network defender is up
against. Closing one of two equivalent doors changes nothing measurable, which
is why "what is the best next fix?" is a badly-posed question on its own, and
why the min-cut has to be computed as a set.

## Why not just apply the ranking greedily, one fix at a time?

Because greedy set-building is not optimal for this problem, and the first
example shows why: after applying the highest-ranked fix (harden the jump
host, cost 20) you still need to close the contractor route, so greedy reaches
a disconnecting set at cost 21 where the optimum is 3. Greedy is seven times
worse here, and nothing in the ranking warns you.

There is also no cheap repair. Recomputing the ranking after each greedy step
does not fix it either — the trap is that the first choice was wrong, not that
the order was.

## The honest caveat: shared fixes

Max-flow minimises the sum of **edge** capacities. When two edges in the cut
name the same fix, that fix's cost is counted twice in the capacity but paid
once in reality. The report shows both numbers and flags the gap:

```
   Note: the cut spans 2 edges but only 1 distinct fixes.
   Max-flow minimised the per-edge total (6); the real bill is
   3, because a shared fix is paid once.
```

The uncomfortable consequence, stated plainly rather than buried: **when fixes
are shared, the cut that minimises the capacity need not minimise the real
bill.** ChokePoint reports a cut that is provably optimal for the capacity
objective, and tells you its true de-duplicated price. It does not claim that
price is optimal.

Optimising the de-duplicated price directly is a genuinely harder problem. It
is no longer a min-cut, because the cost of cutting one edge now depends on
which other edges you cut, and that destroys the structure max-flow relies on.
This is the "independent versus correlated defences" limitation in concrete
form, and it is listed under future work rather than quietly approximated.

## How to read the report

1. **Section 2 is the budget answer.** If you want the attacker out, this is
   the cheapest way, and it is proven.
2. **Section 3 is the triage answer.** If you can only do one thing this
   sprint, start at the top. If the whole column reads `+0`, that is itself
   the finding: your network has redundant attack routes and no single fix
   will move the needle.
3. **A `+0` is not a reason to skip a fix** that section 2 lists. It means
   something else is equally cheap for the attacker, which is an argument for
   doing both, not neither.
