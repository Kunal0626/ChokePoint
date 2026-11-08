# Max-flow, min-cut, and why they answer the patching question

Every number and every trace in this document is produced by a script in the
repository. Regenerate them with:

```bash
.venv/bin/python scripts/explain_mincut.py
```

Machine used for the measured figures at the end: Apple Silicon (arm64),
macOS 26.6.2, Python 3.14.6, networkx 3.7.

---

## 1. Why the min-cut is the right answer to "what is the smallest set of fixes?"

Start from what a set of fixes has to achieve. Applying a fix removes an edge
from the attack graph. A set of fixes is *adequate* exactly when, after
removing all of its edges, no path remains from any entry point to any
target.

"No path remains from source to sink after removing this edge set" is the
definition of a **cut**. So the adequate fix sets and the cuts are the same
objects — not analogous, the same. And if we define each edge's capacity to be
the cost of applying its fix, then the cost of a fix set is the capacity of
its cut.

Therefore:

> the cheapest adequate set of fixes **is** the minimum-capacity cut.

That reframing is the whole design. It also tells us why we can compute it at
all. The number of candidate edge subsets is exponential, so searching fix
sets directly is hopeless. But the **max-flow min-cut theorem** says the
minimum cut's capacity equals the maximum flow's value, and max-flow is
computable in polynomial time. So we compute the easy quantity and read the
cut off the leftovers.

## 2. The worked example

Five nodes. Capacities are fix costs, so this is the default `fixcost` mode.

```
                      (1)
               ┌───────────────> t
               │                 ▲
          (5)  │                 │ (5)
     s ───────> a ──(1)──> c ────┘
     │                     ▲
     └───────> b ──(1)─────┘
          (5)
```

| Edge | Capacity | The fix it represents |
|---|---|---|
| `s->a` | 5 | Patch web app |
| `s->b` | 5 | Mail filtering + training |
| `a->c` | 1 | Firewall SMB from DMZ |
| `a->t` | 1 | Rotate DB credentials |
| `b->c` | 1 | SSH keys only |
| `c->t` | 5 | Restrict DB to app subnet |

Note the shape of the problem: the links next to the internet are *expensive*
to fix and the links in the middle are *cheap*. A human skimming this network
might reach for "patch the web app" first. The algorithm should not.

### 2.1 Running Edmonds-Karp

`SRC` and `SNK` are the virtual super-source and super-sink. They carry
capacity 19 — the sum of all real capacities plus one — so that no cut ever
prefers to sever them.

```
  round 1: push 1 along  SRC->s s->a a->t t->SNK
           running flow = 1
  round 2: push 1 along  SRC->s s->a a->c c->t t->SNK
           running flow = 2
  round 3: push 1 along  SRC->s s->b b->c c->t t->SNK
           running flow = 3
  no augmenting path remains after 3 rounds
```

Each round takes a **shortest** augmenting path, because the search is a BFS.
Round 1 finds the 4-arc route through `a->t`; once that is saturated the
shortest remaining route is 5 arcs, and so on.

### 2.2 The residual graph when it stops

```
  s->a  capacity 5  carrying 2  (3 left)
  s->b  capacity 5  carrying 1  (4 left)
  a->c  capacity 1  carrying 1  (SATURATED)
  a->t  capacity 1  carrying 1  (SATURATED)
  b->c  capacity 1  carrying 1  (SATURATED)
  c->t  capacity 5  carrying 2  (3 left)
```

### 2.3 Reading off the cut

Let **S** be the set of nodes still reachable from the source using leftover
capacity:

```
  S = ['SRC', 'a', 'b', 's']
  the sink is in S: False  (it must not be)
```

The sink cannot be in S — if it were, there would still be an augmenting path
and the algorithm would not have stopped. The cut is every original edge
running from inside S to outside S:

```
    a->c  cost 1   Firewall SMB from DMZ
    a->t  cost 1   Rotate DB credentials
    b->c  cost 1   SSH keys only
  total cut capacity = 3
  max-flow value     = 3
  theorem holds      = True
  networkx.minimum_cut agrees = True (value 3)
```

**Total cost 3, not 5.** The tool recommends three cheap middle-of-the-network
fixes rather than the single expensive perimeter fix a human might have
guessed. That is the output the project exists to produce.

### 2.4 Why the cut's capacity must equal the flow

Two halves, and both are short.

**Every cut is at least the flow.** All flow travels from S to outside S, and
the only way across is the cut's edges. So flow ≤ cut capacity, for *any*
cut. This is the easy direction, and it is why finding any cut gives you an
upper bound on how good a fix set can get.

**This particular cut is exactly the flow.** Every cut edge must be
saturated: if `a->c` had leftover capacity, then `c` would have been reachable
from the source in the residual graph and would have been in S, contradicting
the fact that it is not. So the cut's capacity is the sum of the flows on its
edges, which is the total flow. Combined with the first half, this cut is
minimum and the flow is maximum — neither can improve, because they meet.

Both halves are checked at runtime, not just reasoned about. See section 5.

## 3. Why Edmonds-Karp and not plain Ford-Fulkerson

Ford-Fulkerson is the general method: find *any* augmenting path, saturate it,
repeat. It is correct but underspecified, and the unspecified part — which
path to take — decides whether it is usable.

**Termination.** With integer capacities every augmentation pushes at least 1
unit, so it halts within `max-flow` rounds. But that bounds the work by the
*magnitude of the numbers in the input*, not by the size of the graph. The
standard counterexample is two fat parallel routes joined by a capacity-1
edge:

```
     s ──(1000000)──> a ──(1)──> b ──(1000000)──> t
     └──(1000000)──> b          a ──(1000000)──> t
```

A path choice that keeps routing across the middle edge alternates back and
forth and needs 2,000,000 rounds on a four-node graph. Worse, with irrational
capacities Ford-Fulkerson can fail to terminate at all, converging to a value
below the true maximum.

**The fix.** Edmonds-Karp adds exactly one rule: always take a *shortest*
augmenting path, which means searching with BFS instead of DFS. One can then
prove the shortest augmenting-path length never decreases and each edge can
be the bottleneck only O(V) times, giving O(V·E) augmentations and **O(V·E²)**
overall. The bound no longer mentions the capacities.

That independence is not academic here. `--capacity inverse-difficulty`
produces fractional capacities like 1/7, and the capacity-dependent bound says
nothing useful about those.

### A caveat on that example, because it is easy to overclaim

ChokePoint's test suite contains the million-capacity graph above and checks
it finishes in at most 4 rounds. That check is weaker than it looks, and the
test says so. Running all 120 orderings of its five edges, a stack-based
search and a genuinely recursive DFS *also* finish in at most 4 rounds. The
alternating blow-up the textbook describes needs an adversarial path choice
that none of those orderings actually produces: once one unit crosses the
middle edge it saturates, and the next search simply takes a fat route and
pushes a million units at once.

So what does the suite check instead? The **lemma the bound rests on**:
choosing a shortest augmenting path each round means the shortest augmenting
path length never decreases, which is what limits each edge to being a
bottleneck O(V) times. That property is directly observable and it genuinely
separates the two rules. Measured over 300 seeded graphs at 20 nodes and
60 edges:

| Path selection | Rounds where the path got *shorter* | Graphs affected |
|---|---|---|
| BFS, as implemented | 0 | 0 of 300 |
| Stack / LIFO | 224 | 157 of 300 |

A single round where the length drops is proof the selection rule is not
Edmonds-Karp and the O(V·E²) bound does not apply to it. That is the
assertion `test_augmenting_path_lengths_never_decrease` makes, on every one
of those graphs.

## 4. Residual edges: what they are and why they exist

Push `f` units along an edge of capacity `c` and two things happen. The
forward direction keeps `c - f` units of room. And a **backward** residual
edge of capacity `f` appears.

That backward edge does not correspond to any link in the real network. No
attacker traverses it. It exists so a later augmentation can say: *re-route
`f` units of what I previously sent this way*. Sending flow backwards along it
cancels part of an earlier decision.

Without that, the method would be a greedy heuristic that can paint itself
into a corner. The canonical case:

```
     s ──(1)──> a ──(1)──> b ──(1)──> t
     s ──(1)──> b          a ──(1)──> t
```

Saturate `s->a->b->t` first and the middle edge is full; both remaining routes
appear blocked and the answer looks like 1. The backward residual on `a->b`
lets a second augmentation go `s->b`, *backwards* across `a->b`, then `a->t`
— net effect, two unit-disjoint routes and a correct answer of 2. Residual
edges are how a polynomial algorithm avoids having to be clever about the
order in which it picks paths.

### How often does that actually happen?

Measured over a seeded corpus of 300 random graphs at 20 nodes and 60 edges:

```
  augmentation rounds in total     : 890
  rounds using a backward arc      : 6
  graphs needing at least one      : 6 of 300
```

So on this corpus a backward residual arc is used in **6 of 890 rounds**, and
**2% of graphs** need one at all. This is worth stating precisely, because it
is easy to draw the wrong conclusion in either direction.

Residual edges are rarely *exercised* — BFS's shortest-path rule tends to pick
paths it does not later regret, so the undo capability sits idle most of the
time. But 6 is not 0. On those graphs, an implementation without backward
residuals would report a max-flow that is too low, and therefore a min-cut
that is too cheap: it would tell a defender that fewer fixes suffice than
actually do. For a tool that recommends security work, silently
under-reporting is the worst failure direction available, and it would be
invisible on 98% of inputs.

## 5. The self-checks

Two properties are verified inside the program on every single run, not only
in the test suite:

1. The max-flow value equals the sum of the cut's capacities.
2. Removing the cut's edges really does leave every target unreachable,
   re-tested with a fresh BFS on the original graph.

Check 2 is deliberately written against the original graph and not the
residual structure. A check that reused the residual machinery would share any
bug that produced a bad cut in the first place, and would confirm it rather
than catch it.

A third check asserts no virtual arc appears in the cut, which is what makes
the sentinel-capacity argument in `capacity.py` load-bearing rather than
hopeful.

These raise `SelfCheckError`, an exception — not `assert`. Assertions are
removed by `python -O`, and a tool whose output is a security recommendation
should not be able to quietly stop checking itself because of a flag someone
set for speed.

The reason these live in the program rather than only in `tests/` is simple: a
test suite can only vouch for the graphs it was written against. The self-check
vouches for the graph actually in front of the user.

## 6. Is the minimum cut unique?

The *value* always is. The *edge set* achieving it need not be.

```
  s ->(2)-> m ->(2)-> t : both single-edge cuts cost 2.
  value reported     : 2  (unique)
  edge set reported  : ['Fix the first hop']  (one of two valid answers)
```

ChokePoint reports the cut derived from the residual graph, which is the one
closest to the source side. This is deterministic — the same model always
yields the same recommendation — but a defender should understand that an
equally cheap alternative may exist, and that other considerations (which fix
is faster to deploy, which has less operational risk) might favour it. The
tool is telling you a cheapest answer, not the only one.

## 7. Where this model breaks down in reality

Worth being blunt about, since the output looks authoritative.

**Difficulty and cost numbers are judgement calls.** They are entered by a
human with opinions. Two analysts will produce different graphs for the same
network, and the recommendation can change with them. The tool's value is in
making those assumptions explicit and their consequences computable, not in
being objective.

**Fixes are modelled as independent; real defences correlate.** The min-cut
treats each edge's cost as separate. But one real action ("enforce MFA on the
VPN") may close several modelled links at once, in which case the true cost of
cutting all of them is paid once rather than once per edge. ChokePoint allows
several edges to share a fix *name* and de-duplicates when totalling, but the
min-cut search itself still treats them as independent, so it can overstate
the cost of a cut that happens to reuse a fix. Conversely, one fix can weaken
another's effectiveness, which is not modelled at all.

**Additive difficulty is not how attackers work.** Summing difficulties
assumes effort accumulates linearly and independently along a path. In reality
a foothold changes what comes next — credentials harvested at hop 2 can make
hop 5 trivial — so the real cost of a path is not the sum of its parts.

**Attacker skill is a single global constant, which it is not.** A difficulty
of 8 means something different to a bored teenager and to a funded team. The
model has one attacker.

**Edges are the only thing that can be cut.** Real defenders also remove
hosts, segment networks, and add detection that does not remove a path but
makes using it costly. Only the first of those is expressible, and only
indirectly.

## 8. How you would extend it

**Node cuts.** "Decommission this host" is a node removal, not an edge
removal, and the current model cannot ask for it. The standard technique is
**node splitting**: replace each node `v` with `v_in -> v_out` joined by an
edge whose capacity is the cost of removing the host, redirect every incoming
edge to `v_in` and every outgoing edge from `v_out`, and give the original
edges infinite capacity. A minimum edge cut on the transformed graph is a
minimum node cut on the original. The graph roughly doubles in size and
nothing else about the algorithm changes.

**Probabilities instead of additive difficulty.** If each edge carries a
success probability `p` and the attacker's success along a path is the product
of its edges, then taking `-log p` as the weight turns the product into a sum
and Dijkstra finds the *most likely* attack path unchanged. That is a clean
and genuinely useful substitution. It does **not** carry over to the min-cut:
max-flow needs capacities that add when routes run in parallel, and
probabilities do not add — two independent 0.5 routes give 0.75, not 1.0.
Cutting a probabilistic graph optimally is a different and much harder
problem, related to network reliability, which is #P-hard in general. The
honest answer to "could you just use probabilities everywhere" is no, and
knowing which half survives the change is the interesting part.
