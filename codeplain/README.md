# Codeplain bounty plan (1st = £1,000 cash + $500 credits/member)

**Bounty requirement:** *"Build with \*codeplain as your primary development tool"* +
submit a public GitHub repo. So we can't just call the API once — we must show a real
module that was genuinely **spec-built** with Codeplain, with the `.plain` spec as the
source of truth.

Codeplain renders production code (+ unit/conformance tests) in Python/Go/React from a
structured-English `.plain` spec via its hosted API. Our stack is Python, so we build
one discrete Python module spec-first: **the daily ops-report tool** (`ops_report.plain`
in this folder) — it's self-contained, useful (feeds the pitch's £-at-risk headline and
the Walrus snapshot), and a clean demonstration of spec → code.

## ⚠️ Long pole — do this FIRST (needs a human)
Codeplain isn't self-serve. **Email `support@codeplain.ai` now** to request an API key
(draft below). Everything else is blocked on it.

## Steps once the key arrives
```bash
git clone https://github.com/Codeplain-ai/plain2code_client
cd plain2code_client && pip install -r requirements.txt
export CODEPLAIN_API_KEY=<your key>
python plain2code.py ../golden-coffee/codeplain/ops_report.plain   # renders code + tests into build/
```
Then: commit the `.plain` spec **and** the generated, tested output to the public repo,
and in the README/demo state "the ops-report module was built spec-first with Codeplain;
the `.plain` file is the source of truth." That makes Codeplain the *primary* tool for a
real deliverable — a defensible claim for the bounty.

## Stretch
If it's smooth, spec a second module the same way (e.g. an eval scorer) to make the
"primary tool" claim stronger across more of the codebase.

---

## Email draft to send to support@codeplain.ai

> Subject: API key request — Encode Vibe Coding Hackathon (Golden Coffee)
>
> Hi Codeplain team,
>
> We're building **Golden Coffee** (an AI café/restaurant ops copilot) at the Encode
> Vibe Coding Hackathon this weekend and would love to use Codeplain as our primary
> development tool for the Codeplain bounty. Could you please issue us an API key for
> the `plain2code_client`?
>
> Team: <names + emails>. Public repo: https://github.com/lukataylo/Golden-Coffee
>
> Thanks very much — excited to build spec-first with `*plain`.
