# dmz — a textbook perimeter, with one rule nobody removed

Internet → external firewall → DMZ (web server, mail relay) → internal
firewall → internal network (app server, administrator workstation,
database). **Target: the internal database.**

The architecture is correct. One rule is not: a temporary DMZ-to-database
firewall rule, opened for a data migration, was never removed.

Output: [`output/dmz/report.txt`](output/dmz/report.txt) ·
[picture](output/dmz/network.png) · [`network.dot`](output/dmz/network.dot) ·
[what-if](output/dmz/whatif-remove-legacy-rule.txt)

## Why these numbers

| Edge | Difficulty | Reasoning |
|---|---|---|
| `internet → fw_ext` | **1** | Sending packets at a published service. Anyone can. |
| `dmz_web → db_internal` | **2** | **The misconfiguration.** The rule is open; there is nothing to exploit. |
| `admin_ws → db_internal` | **2** | Administrators hold standing access. No exploit needed. |
| `app_internal → db_internal` | **3** | The application's own credentials, which are on the application server by design. |
| `fw_ext → dmz_web` / `→ dmz_mail` | **4** | Public exploit, or phishing through the relay. Routine against internet-facing services. |
| `fw_int → app_internal` | **5** | Abusing traffic the firewall is *supposed* to permit. Needs care. |
| `dmz_mail → admin_ws` | **6** | Phishing a named administrator. Plausible, and more effort than a bulk campaign. |
| `dmz_web → fw_int` / `dmz_mail → fw_int` | **7** | Traversing a correctly configured internal firewall. This is the control working. |

## Modelling an edge nobody can fix

`internet → fw_ext` carries a fix cost of **40**, named "Withdraw all
internet-facing services (not practical)".

That is deliberate, and it is a technique rather than a fudge. The business
exists to serve traffic, so the firewall must accept it; the edge is real and
must be in the graph, but it is not available as a remediation. Without a
prohibitive cost the min-cut would "solve" the problem for 1 by cutting the
single edge at the front door, which is both optimal and useless.

A high finite cost is better than omitting the edge, because the edge is
genuinely traversable and leaving it out would understate the attacker's
options. It is also better than infinity: the arithmetic stays exact, and the
edge still appears in the single-fix ranking, where it is informative.

## What the tool found

```
cheapest attack cost: 7

  #1  (7)  internet -> fw_ext -> dmz_web -> db_internal           <-- the shortcut
  #2 (13)  internet -> fw_ext -> dmz_mail -> admin_ws -> db_internal
  #3 (20)  internet -> fw_ext -> dmz_web -> fw_int -> app_internal -> db_internal

minimum fix set — total cost 8
   4  Mail filtering and DMARC enforcement
   3  Least-privilege database account for the application
   1  Remove the legacy DMZ-to-database firewall rule
```

**It finds the shortcut, and the gap is the whole story.** Path #1 is the
leftover rule at cost **7**. Path #3 is the same attacker going the way the
architecture intended — through the internal firewall — at cost **20**.

One forgotten rule makes the network **about three times easier** to attack
than its design implies. The picture shows it as the long curve sweeping under
the internal firewall and the app server, which is precisely what it does.

## The what-if

```
   Cheapest attack cost before : 7
   Cheapest attack cost after  : 13
   Raised the attacker's cost by : +6

   Of the original top 3 paths, 2 of 3 did not use this fix.
```

Deleting one firewall rule — **cost 1, measured in minutes** — raises the
attacker's cost from 7 to 13. Note what it does *not* do: it does not restore
the 20-cost design, because the administrator-phishing route at 13 is still
cheaper than the intended path. Fixing the obvious thing reveals the next
thing, which is how this work actually goes.

## The ranking's top entry is a trap

```
   fix                                               cost  after  raises  paths
   Withdraw all internet-facing services (not pra      40    CUT     all    3/3
   Patch the DMZ web application and deploy a WAF       5     13      +6    2/3
   Remove the legacy DMZ-to-database firewall rule      1     13      +6    1/3
   Least-privilege database account for the applic      3      9      +0    1/3
```

The single most effective fix available is to unplug the company from the
internet. It ranks first because it is the only one that fully disconnects the
target, and the ranking sorts disconnection above every finite improvement.

It is also, at cost 40, something no one will ever do — which is exactly why
the minimum fix set exists alongside the ranking and never selects it. Read
together the two sections say: *the most effective thing is impossible; here
is the best thing you can afford, for 8.*

Rows two and three are the sharper lesson. Patching the web app and deleting
the legacy rule both raise the attacker's cost by the same **+6**. One costs
**5**; the other costs **1**.
