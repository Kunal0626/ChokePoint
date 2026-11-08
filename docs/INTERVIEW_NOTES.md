# Interview notes

Part 1 is the design decisions, each with the alternative that was rejected
and why. Part 2 is the fifteen hardest questions an interviewer could ask,
with short answers.

Nothing here is aspirational. Every claim is either in the code or in a
measurement under `docs/`.

---

# Part 1 — design decisions

### 1. One super-source and one super-sink, not per-pair analysis

A model can have several entry points and several targets. Shortest-path and
max-flow are both defined for a single source and sink.

**Alternative:** run one analysis per `(entry, target)` pair and combine.
**Why not:** for shortest paths the two agree, and the super-source version is
just faster. For the min-cut they **disagree** — the union of per-pair minimum
cuts is not a minimum cut of the joint problem, so the per-pair approach
over-recommends fixes. Since "the smallest set of fixes" is the product, that
is wrong in exactly the way that matters.

### 2. Difficulty and capacity are different numbers on the same edge

Difficulty is attacker effort and drives Dijkstra and Yen. Capacity is
defender cost and drives max-flow.

**Alternative:** one weight per edge. **Why not:** the easiest bug in this
project is to min-cut on difficulty, which silently answers "where is the
attacker most constrained?" when you asked "what is the cheapest set of
fixes?" Both are reasonable questions; getting the wrong one without noticing
is the failure mode. Keeping them as separate derived views makes the mistake
hard to write.

### 3. Exact arithmetic, floats rejected at the boundary

`fixcost` and `unit` are integers; `inverse-difficulty` uses
`fractions.Fraction`. The loader refuses floats outright, including `4.0`.

**Alternative:** accept floats and coerce. **Why not:** the min-cut self-check
asserts max-flow equals the sum of cut capacities. With floats that comparison
becomes a coin flip on any graph where rounding accumulates, and the check
either fires spuriously or passes while being slightly wrong. Refusing at the
boundary means one place enforces the invariant instead of every downstream
module defending itself.

### 4. Edges are an indexed tuple, not a nested-dict adjacency

**Alternative:** `adj[u][v] = weight`, the version almost everyone writes
first. **Why not:** it silently collapses parallel edges. Two techniques
between the same hosts are two distinct ways in with two distinct fixes;
collapsing them understates both the path count and the min-cut cost. Index
identity also survives into the residual graph, where one pair per *arc*
rather than per node pair is what lets parallel edges be cut independently.

### 5. Yen compares root paths by arc, not by node

The textbook formulation compares node sequences.

**Alternative:** follow the textbook. **Why not:** with parallel edges two
paths can have identical node lists and different edges, so node comparison
bans the wrong arc. Comparing arc sequences is what makes the implementation
correct on multigraphs rather than merely correct on the paper's examples.

### 6. Loopless paths, not k-shortest walks

**Alternative:** let Dijkstra pop a node more than once — far simpler.
**Why not:** it returns walks that revisit hosts. On a graph with `a→b`, `b→a`
and `b→c` it happily reports `a-b-a-b-c` as the second-best route. An attacker
who already controls a host gains nothing by compromising it again.

### 7. Self-checks run in the program, and raise rather than assert

Three checks on every invocation: flow equals cut capacity, no virtual arc in
the cut, and a fresh BFS confirms the target is unreachable once the cut is
removed.

**Alternatives:** check only in tests, or use `assert`. **Why not:** a test
suite vouches only for the graphs it was written against; the self-check
vouches for the graph in front of the user. And `assert` vanishes under
`python -O`, so a tool emitting security advice could silently stop checking
itself because someone set a flag for speed. The third check is deliberately
written against the *original* graph, not the residual structure — a check
reusing the residual machinery would share any bug that produced the bad cut
and would confirm it rather than catch it.

### 8. Validation collects every problem before raising

**Alternative:** raise on the first bad field. **Why not:** that produces a
fix-one-line-and-rerun loop, miserable on a 40-edge model. The cost is that
every check must keep going after a failure, and that cascades have to be
suppressed deliberately — a broken `nodes` list must not generate a dozen
"unknown node" errors that are really one error.

### 9. Lazy `heapq` instead of decrease-key

**Alternative:** maintain a heap index and sift manually. **Why not:** about
fifty lines of error-prone bookkeeping to turn O(E) heap entries into O(V).
Since E ≤ V², log E ≤ 2 log V, so the bound is the same O((V+E) log V) either
way. Measured at n^1.03 over 100–2,000 nodes.

### 10. Virtual arcs get `sum(real capacities) + 1`, not infinity

**Alternatives:** omit virtual arcs, or use `float('inf')`. **Why not:**
infinity drags floats into arithmetic required to stay exact, and `inf - x ==
inf` breaks residual bookkeeping during augmentation. The finite sentinel is
provably large enough: the cut taking the super-source plus every non-target
node crosses only real edges, so its capacity is at most the real total, which
is strictly below the sentinel.

### 11. Fix names are deliberately not unique

**Alternative:** one fix per edge. **Why not:** one real action ("enforce MFA
on the VPN") can close several modelled links, and applying it should close
all of them. The price is that max-flow prices each edge separately, so a cut
containing two edges with one fix name double-counts. The report shows both
the capacity and the real de-duplicated bill, and the docs say plainly that
the capacity-optimal cut need not be the bill-optimal one.

### 12. Paths are flattened to self-contained hops immediately

**Alternative:** keep edge indices on paths. **Why not:** the what-if analysis
derives modified copies of the network, and an index into the original is
meaningless in a copy that has had edges removed. (The renderer does need
indices, so `FixSet` and `Analysis` carry them explicitly, documented as
relative to the analysed network.)

### 13. Exit code 3 is separate from exit code 2

**Alternative:** one error code. **Why not:** 2 means "your model needs
fixing"; 3 means "this tool computed something it could not verify and you
should not trust the output". Collapsing them would let a real bug look like a
user error.

### 14. The `.dot` file is always written; the image is a convenience

**Alternative:** depend on Graphviz, or on a Python binding. **Why not:**
runtime dependencies stay empty, and `.dot` is text — it reviews and commits
cleanly and renders at any size later. Graphviz is invoked, if present, as a
subprocess with a fixed argument list and no shell. The matplotlib fallback
exists because on the development machine neither Graphviz nor Homebrew is
installed, so the fallback *is* the live path.

### 15. Hand-rolled layered layout with barycentre ordering

**Alternative:** order nodes within a column alphabetically. **Why not:** it
scatters each node's predecessors up and down the previous column and the
edges cross far more than necessary. Targets are also pinned to their own
rightmost column, because a target two hops from the internet would otherwise
be drawn mid-picture, which reads as unimportant when it is the whole point.

---

# Part 2 — the fifteen hardest questions

### 1. Why is the minimum cut the right answer to "what is the smallest set of fixes"?

Not by analogy — by definition. Applying a fix removes an edge. A set of fixes
works if and only if removing its edges leaves no path from any entry to any
target, which is the definition of a cut. Define capacity as the cost of the
fix and the cost of a fix set is the capacity of its cut. So "cheapest
adequate fix set" and "minimum-capacity cut" are the same object.

That also makes it computable. Enumerating fix subsets is exponential; the
max-flow min-cut theorem says the minimum cut's capacity equals the maximum
flow's value, and max-flow is polynomial. We compute the easy quantity and
read the cut off the residual graph.

### 2. Why Edmonds-Karp and not plain Ford-Fulkerson?

Ford-Fulkerson says "find any augmenting path, saturate, repeat" and never
says which path. With integer capacities it halts within `max-flow` rounds —
but that bounds work by the *magnitude of the numbers*, not the size of the
graph, and with irrational capacities it need not terminate at all.

Edmonds-Karp adds one rule: always take a **shortest** augmenting path, i.e.
BFS not DFS. The shortest augmenting-path length then never decreases, each
edge can be the bottleneck only O(V) times, giving O(V·E) augmentations and
O(V·E²) overall — a bound that does not mention the capacities. That matters
here because `inverse-difficulty` produces fractional capacities.

### 3. What are residual edges, given no attacker can traverse one?

Pushing `f` units along an edge of capacity `c` leaves `c − f` forward room
and creates a **backward** residual edge of capacity `f`. It corresponds to
nothing in the real network. It exists so a later augmentation can say
"re-route `f` units of what I previously sent this way".

Without it the method is a greedy heuristic that paints itself into a corner.
Saturate `s→a→b→t` on the four-node example and both remaining routes look
blocked, answer 1; the backward residual on `a→b` lets a second augmentation
go `s→b`, backwards across `a→b`, then `a→t`, for the correct 2.

**And the error direction matters:** an implementation without backward
residuals reports a max-flow that is too *low*, hence a min-cut that is too
*cheap* — it tells a defender fewer fixes suffice than actually do. I measured
how often this bites: across 300 seeded graphs, only 6 of 890 augmentation
rounds used a backward arc, and only 2% of graphs needed one. Rarely
exercised, never optional, and invisible on 98% of inputs.

### 4. How does this model fail in reality?

Four ways, roughly in order of severity.

*Correlated defences.* The min-cut prices each edge independently. One real
action can close several links, and one fix can weaken another's
effectiveness. ChokePoint handles the first case partially (shared fix names,
de-duplicated in the report) and not at all in the search.

*Additive difficulty.* Summing assumes effort accumulates independently.
Credentials harvested at hop 2 can make hop 5 trivial.

*One attacker.* A difficulty of 8 means different things to a bored teenager
and a funded team.

*Subjective inputs.* The numbers are judgement. Two analysts produce two
graphs. The honest defence is not that they are objective but that they are
explicit and their consequences computable — change a 3 to a 4 and see
whether the answer moves.

### 5. How would you extend this to node cuts?

"Decommission this host" is a node removal, which the current model cannot
express. The standard technique is **node splitting**: replace each node `v`
with `v_in → v_out` joined by an edge whose capacity is the cost of removing
the host, point every incoming edge at `v_in` and every outgoing edge out of
`v_out`, and give the original edges infinite capacity. A minimum edge cut on
the transformed graph is a minimum node cut on the original. The graph roughly
doubles; nothing about the algorithm changes.

### 6. And probabilities instead of additive difficulty?

Half of it works cleanly and half does not, and knowing which is the
interesting part.

If each edge carries a success probability `p` and path success is the
product, then taking `−log p` as the weight turns the product into a sum and
**Dijkstra is unchanged** — it finds the most likely attack path.

It does **not** carry over to the min-cut. Max-flow needs capacities that add
when routes run in parallel; probabilities do not — two independent 0.5 routes
give 0.75, not 1.0. Cutting a probabilistic graph optimally is a different and
much harder problem related to network reliability, which is #P-hard in
general.

### 7. Your tool prints a minimum fix set *and* a ranking of individual fixes. Why both?

They answer different questions and can give opposite advice. In the hub
example in `docs/MINCUT_VS_GREEDY.md` the single most effective fix (+15,
touching 2 of 3 paths) is in **no** minimum cut, and all three members of the
cost-3 cut raise the attacker's cost by **+0** individually.

So: *"spend 20 and their cheapest route gets six times harder"* versus
*"spend 3 and there is no route at all"*. Both are correct. The `home_lab`
example shows the ranking degenerating entirely — every fix scores +0, because
two independent routes cost 5 each. Greedy single-fix analysis is blind to
redundancy, and redundancy is what a defender actually faces.

### 8. Then why not build the fix set greedily from the ranking?

Because greedy is not optimal here, and badly so. On the hub example, taking
the top-ranked fix first (harden the jump host, cost 20) still leaves the
contractor route open, so greedy reaches a disconnecting set at cost **21**
where the optimum is **3** — seven times worse, with nothing in the ranking to
warn you. Recomputing the ranking after each step does not help: the first
choice was wrong, not the order.

### 9. Two edges in your min-cut share one fix. What does max-flow think it costs, what does it cost, and is the cut still optimal?

Max-flow minimised the per-edge total, so it counted that fix twice. You pay
it once, so the real bill is lower; the report prints both.

The cut is still provably optimal **for the capacity objective**. It is not
necessarily optimal for the de-duplicated bill, because once fixes are shared
the cost of cutting one edge depends on which others you cut — which destroys
the structure max-flow relies on and makes it no longer a min-cut problem. The
docs say this rather than approximating it quietly.

### 10. Why does Dijkstra require non-negative weights?

Its correctness rests on the claim that when a node is popped its distance is
final, which holds only if extending a path can never make it cheaper. With
`A→B` at 2, `A→C` at 5 and `C→B` at −4, Dijkstra settles B at 2 and later
finds 1, discards the improvement, and returns 2.

It matters for the *model*, not just the code: it is why "this step makes the
attacker's life easier" cannot be a negative difficulty. The 1–10 scale keeps
every real weight positive, and virtual arcs weigh exactly 0, which is fine —
the requirement is non-negative, not positive.

### 11. Your `heapq` has no decrease-key. What did you do, and what did it cost?

Lazy deletion: push a duplicate entry and skip any popped entry for an
already-settled node. The heap holds O(E) entries instead of O(V), so the
bound is O((V+E) log E); since E ≤ V², that is the same O((V+E) log V) up to a
constant.

A thing I got wrong and corrected: I assumed the staleness check was part of
*correctness*. Mutation testing showed removing it changes no answer — with
non-negative weights a stale pop carries an inflated distance and every
candidate it generates loses the `candidate < known` comparison anyway. It is
a **performance** optimisation worth about 19% (21.5 ms versus 25.5 ms over
300 graphs). Correctness lives in the comparison.

### 12. You claim your implementation is Edmonds-Karp and not Ford-Fulkerson. Prove it.

Not with the textbook million-capacity graph, which I checked and which does
**not** discriminate: across all 120 orderings of its five edges, a
stack-based search and a genuinely recursive DFS also finish in at most 4
rounds. Once a unit crosses the middle edge it saturates and the next search
takes a fat route and pushes a million units at once.

The discriminating property is the lemma the bound rests on: under
shortest-augmenting-path selection the path length never decreases between
rounds. Over 300 seeded graphs, BFS produced **0** decreases and a stack-based
search produced **224** across 157 graphs. That is the assertion the test
makes, and swapping the queue for a stack now fails 65 tests.

### 13. How do you know your tests would catch a bug?

By breaking the code on purpose and checking they go red. Every algorithm
module was mutation-tested — around forty deliberate defects across Dijkstra,
Yen, Edmonds-Karp, the capacity modes, the recommendation layer and the
renderers.

Three escapes were genuinely informative. One (removing Dijkstra's staleness
check) turned out not to be a bug at all. Two were real gaps in my tests: the
BFS-vs-DFS test that proved nothing, and a ranking test that never mixed a
disconnecting fix with a merely-slowing one, leaving that term unguarded. Both
are now covered.

### 14. Your renderer passed all its tests and still drew two wrong pictures. What does that tell you?

That test suites verify properties you thought to state, and a diagram's job —
being readable — is hard to state. The two bugs: opposite-direction edges
drawn exactly on top of each other, because I keyed curvature on the *ordered*
pair, so one edge's colour silently replaced the other's; and edge labels
placed on the wrong side of their curves, because matplotlib's `arc3` bows the
opposite way from my derivation.

I found both by rendering a picture and looking at it, and fixed the second by
drawing an arc and a candidate point together rather than reasoning harder.
The lesson is to know which properties your tests cannot reach and to inspect
those directly.

### 15. Your benchmark shows Edmonds-Karp at n^1.56 against a bound of n³. Is your implementation better than the bound, or is your benchmark easy?

The benchmark is easy, and the reason is measurable. The O(V·E) bound on
augmentations is an adversarial worst case; what actually drives the round
count is the max-flow value, since most augmentations push one unit. I
recorded both: augmentations track the cut value closely (310 against 314 at
1,000 nodes; 470 against 470 at 2,000) and both grow as **n^0.52**. Each
augmentation is one linear BFS, so n^0.52 × n^1.00 predicts **n^1.52** against
**n^1.56** measured.

And that n^0.52 is a property of my generator, not the algorithm: it uses
about √n layers, so the narrowest layer boundary holds O(√n) nodes. Widen the
layers and the exponent rises. O(V·E²) remains the right bound to quote,
because it is the only one that holds whatever graph arrives.
