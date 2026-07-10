# Outreach Playbook — Batch 1 (30 agencies)

The first 30 emails are **customer interviews disguised as sales outreach**.
The KPI is learning, not subscriptions.

## Success criteria (evaluate after ~1 week)

- [ ] 5+ agencies responded at all
- [ ] 3+ asked questions or requested another report
- [ ] 1+ said they'd pay or run a pilot

**Silence is not product failure** — wrong contact, inbox overload, bad
timing, agency already at capacity. Only engaged replies carry signal.
Do not change the product based on non-responses.

**The milestone that matters:** an agency asking *"can you send me next
week's report too?"* — that means the report entered someone's workflow.
Until that happens, build nothing new.

## When a reply lands

Send the current `samples/intent_report_*.md` (or paste it into the email),
then work these questions naturally into the conversation — never as a
survey:

1. Which company caught your eye first?
2. Any company you'd call a bad recommendation? Why?
3. Did you already know about any of these? (dedupe-vs-their-sources test)
4. What's missing that you'd need before contacting one of them?
5. Would you want this every Monday?
6. What would you actually pay? (anchor was $149/mo — listen, don't defend)

Log every answer in `prospect_list.csv` Notes and update
`samples/tracking.csv` (AgencyContacted / Reply / Meeting / ClosedDeal).

## Reply template for "send it"

> Here it is — this week's 12. Two I'd look at first: [top High-confidence
> company] and [second]. Curious which one catches your eye — and if any of
> them feel off, tell me, that feedback directly tunes next week's list.
>
> If it's useful I'll send a fresh one every Monday, tuned to [their niche].
> First few are on me.

## Weekly loop

1. Monday: `python report.py --days 7 --top 12 --out samples`
2. Sanity-read the report — would *you* pay for it this week?
3. `python send_outreach.py --limit 30` (next unsent batch)
4. Log replies + interview answers same day they arrive
5. Friday: compare which report companies got mentioned in replies vs
   which signals ranked them — that comparison is the V2 spec

## What V2 gets decided by

Reply-rate evidence in `tracking.csv` + interview answers. Not intuition,
not more scoring tweaks, not this playbook's author.
