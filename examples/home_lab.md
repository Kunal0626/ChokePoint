# home_lab — a flat home network

A router, two laptops, a NAS holding the family photos, an IoT camera and a
smart TV on the same flat network, a guest Wi-Fi, and a Raspberry Pi running
Pi-hole. **Target: the NAS.**

Two entry points, not one: `internet`, and `guest_wifi` — because anyone
within radio range can join the guest network, and that is a genuinely
different starting position from the open internet.

Output: [`output/home_lab/report.txt`](output/home_lab/report.txt) ·
[picture](output/home_lab/network.png) · [`network.dot`](output/home_lab/network.dot)

## Why these numbers

| Edge | Difficulty | Reasoning |
|---|---|---|
| `guest_wifi → iot_camera` | **1** | Default credentials on a consumer camera. No skill, publicly documented. |
| `guest_wifi → router` | **2** | Guest SSID sharing one flat LAN. Nothing to exploit — the isolation was simply never switched on. |
| `laptop_* → nas` | **2** | The share is already mapped with saved credentials. Owning the laptop *is* owning the NAS. |
| `internet → laptop_kid` | **3** | Phishing a teenager. Routine. |
| `internet → laptop_adult` | **4** | Same technique, slightly more caution assumed. |
| `internet → router` | **6** | Needs an unpatched firmware bug and WAN admin exposed. Real, but not casual. |
| `internet → smart_tv` | **7** | Modern TV firmware is a harder target than its reputation suggests. |

Fix costs are mostly **1** because home fixes are settings, not projects. The
exceptions are "unique passwords in a password manager" (**2** — it is a
habit change for a household, not a checkbox) and "put the NAS on its own
VLAN" (**3** — it needs a capable router and will break something on first
attempt).

## What the tool found

```
cheapest attack cost: 5

  #1 (5)  guest_wifi -> router -> nas
  #2 (5)  internet -> laptop_kid -> nas
  #3 (6)  internet -> laptop_adult -> nas

minimum fix set — total cost 5
   3  Put the NAS on its own VLAN
   1  Remove saved NAS credentials from laptops   (closes 2 links)
   1  Update TV firmware and disable its app store
```

**The cheapest way in is the guest Wi-Fi**, tied with phishing a laptop. Both
cost the attacker 5. The expensive-looking router firmware exploit never
features; the attacker has no reason to work that hard.

## The thing worth studying here

Look at the single-fix ranking:

```
   fix                                       cost  after  raises  paths
   Remove saved NAS credentials from laptops    1      5      +0    2/3
   Family security awareness and browser hard   2      5      +0    2/3
   Enable guest network isolation               1      5      +0    1/3
   Put the NAS on its own VLAN                  3      5      +0    1/3
```

**Every single fix raises the attacker's cost by +0.** Not one of them moves
the number, so the ranking is worthless for choosing.

That is not a bug, and it is the most useful thing this example teaches. There
are two independent routes to the NAS that both cost 5. Close the guest
network and the attacker phishes the laptop. Clean the laptop and they use the
guest network. Any *single* fix leaves an equally cheap alternative.

The min-cut is unmoved by this, because it reasons about sets: three fixes,
total cost 5, and the NAS is unreachable. A greedy "do the highest-impact
thing" process would have stalled at the first step with nothing to
recommend.

A real home network looks exactly like this — redundant, flat, with several
equally soft ways to the same box. `docs/MINCUT_VS_GREEDY.md` works through
why the two sections disagree.

## Also demonstrated: one fix closing two links

```
   Note: the cut spans 4 edges but only 3 distinct fixes.
   Max-flow minimised the per-edge total (6); the real bill is
   5, because a shared fix is paid once.
```

"Remove saved NAS credentials from laptops" is one action that closes both
`laptop_kid → nas` and `laptop_adult → nas`. Max-flow counts its cost twice
because it minimises a per-edge total; you pay it once. The report shows both
figures rather than quietly picking one.
