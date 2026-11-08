# small_company — a 150-person Windows estate

Internet, a public web server, webmail, a VPN concentrator, a mail server,
employee workstations, a file server, a domain controller, a backup server,
and a production database. **Target: the production database.**

Output: [`output/small_company/report.txt`](output/small_company/report.txt) ·
[picture](output/small_company/network.png) ·
[`network.dot`](output/small_company/network.dot)

## Why these numbers

| Edge | Difficulty | Reasoning |
|---|---|---|
| `vpn → workstations` | **2** | No exploit at all. The VPN lands clients on the flat user VLAN, so arriving *is* arriving. |
| `workstations → fileserver` | **2** | A share readable by all staff. Normal user rights are enough. |
| `dc → db_prod` | **2** | Domain admin can log in anywhere. Trivial *once you are domain admin* — the difficulty is in the hop before. |
| `internet → mail` | **3** | Phishing a 150-person company. Someone always clicks. |
| `internet → web`, `→ owa`, `→ vpn` | **4** | Public exploit against an unpatched app, or password spraying without MFA. |
| `web → db_prod` | **5** | Credentials in a config file, but you must get code execution first. |
| `workstations → dc` | **6** | Credential dumping and pass-the-hash. Well documented, but needs local admin and a privileged session to catch. |

Fix costs reflect coordination, not typing. "Tighten file share permissions"
is **2** — a day, plus finding out what breaks. "Deploy LAPS and Credential
Guard" is **6** — a rollout across every workstation. "Tiered admin model,
database not domain-joined" is **8**: a re-architecture that will be argued
about for a quarter.

## What the tool found

```
cheapest attack cost: 9

  #1  (9)  internet -> web -> db_prod
  #2 (12)  internet -> mail -> workstations -> fileserver -> db_prod
  #3 (12)  internet -> vpn  -> workstations -> fileserver -> db_prod

minimum fix set — total cost 12
   6  Deploy LAPS and Credential Guard
   4  Move secrets to a vault and restrict the database to the app subnet
   2  Tighten file share permissions
```

## The thing worth studying here

**The cheapest adequate fix set is entirely inside the network.** Not one
perimeter control appears in it.

That is worth dwelling on, because the perimeter is where the instinct goes.
Closing the four internet-facing edges — patch the web app, deploy a WAF,
enforce MFA, filter mail — would also disconnect the database. It costs
**13**, and it is *more* expensive than the interior answer at **12**,
despite MFA being shared across two edges and therefore counted once.

So the tool's advice is: let the attacker have the web server and the mailbox.
Make sure that getting them is worth nothing. Three fixes — stop secrets
sitting in a config file, stop the file server handing out connection strings,
stop a workstation becoming domain admin — and every route dies.

That is a real argument that a defender could take to a budget meeting, and
it is the opposite of what a vulnerability scanner's severity-sorted list
would have told them.

## And the ranking disagrees, as usual

```
   fix                                                  cost  after  raises  paths
   Move secrets to a vault and restrict the database       4     12      +3    1/3
   Patch web application and deploy a WAF                  5     12      +3    1/3
   Secrets hygiene audit of the file server                2      9      +0    2/3
   Tighten file share permissions                          2      9      +0    2/3
```

The best single fix raises the attacker's cost from 9 to 12 — it closes the
fast route through the web server and forces them onto a 12-cost detour. It
does not stop them.

Note that "Patch web application and deploy a WAF" achieves exactly the same
+3 for cost 5, where the vault fix costs 4. Equal effect, higher price: that
is why the ranking breaks ties on cost, and why the cheaper one is listed
first.
