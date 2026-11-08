# Example networks

Three hand-made models, with the reasoning behind every number.

| Model | Scenario | Target | What it demonstrates |
|---|---|---|---|
| [`home_lab.json`](home_lab.json) · [notes](home_lab.md) | Flat home network | NAS with family photos | Several entry points; a shared fix; a single-fix ranking that is entirely uninformative |
| [`small_company.json`](small_company.json) · [notes](small_company.md) | 150-person Windows estate | Production database | The cheapest fix set is *inside* the network, not at the perimeter |
| [`dmz.json`](dmz.json) · [notes](dmz.md) | Internet → firewall → DMZ → internal firewall → internal | Internal database | One misconfiguration creating a shortcut, and how to model an edge nobody can fix |

Regenerate everything under `output/` with:

```bash
./scripts/run_examples.sh
```

`tests/test_examples.py` fails if the committed output drifts from what the
code currently produces, so the numbers quoted in these notes cannot go stale
without the suite noticing.

---

## The scales, and why they are defensible

The headline risk with a tool like this is that it launders a guess into a
number that looks authoritative. The defence is not to pretend the numbers are
objective — they are not — but to write down the rubric, apply it
consistently, and let a reader disagree with a specific edge rather than with
the whole output.

### Difficulty, 1–10: effort for the *attacker*

| | Meaning | Typical |
|---|---|---|
| **1–2** | No credentials and no skill. Publicly documented, point-and-click. | Default password, open share, guest network not isolated |
| **3–4** | A known vulnerability with a public exploit, a guessable password, or a user who clicks. | Unpatched web app, phishing, password spraying |
| **5–6** | Needs credential reuse, a chain of steps, or real familiarity with the environment. | Credentials found on disk, pass-the-hash, internal phishing |
| **7–8** | A hardened or well-monitored target; needs a working pivot or specialist knowledge. | Traversing a correctly configured firewall, modern IoT firmware |
| **9–10** | Needs original research, an unpublished vulnerability, or physical access. | *Not used in these examples — none of these scenarios warrant it* |

Two conventions worth stating because they are easy to get wrong:

* **Difficulty is per-hop, not cumulative.** The cost of a path is the sum, so
  the model already accounts for a long route being more work.
* **Difficulty describes the step, not the prize.** Reaching a database is no
  harder because it is valuable. Importance is expressed by making it a
  target, not by inflating the difficulty of getting there.

### Fix cost: effort for the *defender*

Read as rough engineer-days, including the coordination, not just the typing.

| | Meaning | Typical |
|---|---|---|
| **1** | A setting. Hours, no change window. | Change a default password, delete a firewall rule, disable UPnP |
| **2–3** | A day or two, maybe a change window. | Tighten share permissions, roll out MFA, a secrets audit |
| **4–6** | A week or more, several teams. | Deploy EDR, a WAF, LAPS and Credential Guard |
| **8–10** | A project. Procurement, migration, or re-architecture. | Tiered admin model, taking a database out of the domain |
| **20+** | Deliberately prohibitive: used to mark an edge that *cannot* be cut. | See [`dmz.md`](dmz.md) |

### What these numbers are not

They are one practitioner's judgement, written down. Two analysts would
produce two different graphs for the same network and could get different
recommendations. That is a property of the problem, not a defect in the tool.

What the tool adds is that the assumptions are now **explicit and their
consequences computable**: you can argue about whether phishing really is a 3,
change it, re-run, and see immediately whether the recommendation moves. An
argument about a single number is a much better conversation than an argument
about a vague feeling that the web server is the risky one.

`docs/MAXFLOW_MINCUT.md` §7 covers where the model breaks down more fully.
