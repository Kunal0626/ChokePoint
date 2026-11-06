# ChokePoint

**Attack-path and patch-priority analyzer**

> Status: In progress. Code is being built and will be added here.

Models a network as a graph and answers two questions: how would an attacker reach the crown-jewel asset, and which few fixes would cut off every route?

## How it works
1. Hosts are nodes; exploit difficulty sets edge weights in a directed graph.
2. Dijkstra finds the cheapest route from the entry point to the critical asset.
3. Max-flow (Edmonds-Karp) computes the bottleneck; the min-cut is the smallest set of links to fix.
4. Output is a ranked patch list plus a graph picture with the cut edges highlighted.

## Stack
- Python
- Dijkstra
- Edmonds-Karp max-flow
- Graphviz / matplotlib

## CS concepts
- Shortest paths (DAA)
- Max-flow / min-cut
- Graph modelling
- Risk prioritisation

## Roadmap
- [ ] JSON input format for hosts, links and difficulty
- [ ] Dijkstra (own implementation) and top-k paths
- [ ] Edmonds-Karp max-flow and min-cut extraction
- [ ] Ranked patch recommendations
- [ ] Graph visualisation with the cut highlighted
- [ ] Two or three hand-made example networks
- [ ] Runtime test on a ~1,000-node random graph

## Usage
Coming soon.

---
Part of my portfolio: [github.com/Kunal0626](https://github.com/Kunal0626)
