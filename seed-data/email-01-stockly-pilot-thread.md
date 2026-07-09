# Email Thread — Stockly Pilot Results & Next Steps (Internal, dummy data)

---
**From:** Santosh Thota <santosh@analytos.ai>
**To:** Narayan Laksham <narayan@analytos.ai>; Ashok Suthar <ashok@analytos.ai>
**Subject:** Stockly pilot — 90-day numbers are in
**Date:** Mon, 15 Jun 2026 09:42

Narayan, Ashok —

Final 90-day readout from the precision machining pilot:

- On-hand inventory value down 21% (target was 15%, so we beat it)
- Stockout events down 35%
- Planner replenishment review time: 6 hrs/week → 55 min/week
- 3,412 SKUs live on digital kanban loops, Monte Carlo sim running nightly in ~14 min

Two learnings worth capturing: (1) the demand-shift detector caught a phase-out SKU the planner had missed — that alone freed ~$85K of dead stock; (2) plant floor adoption only clicked after we turned on Tier 2 autonomy (auto-adjust with approval). Tier 1 recommend-only was getting ignored.

Santosh

---
**From:** Narayan Laksham <narayan@analytos.ai>
**To:** Santosh Thota; Ashok Suthar
**Subject:** RE: Stockly pilot — 90-day numbers are in
**Date:** Mon, 15 Jun 2026 11:17

Great numbers. Three asks:

1. These proof points are approved for external use — but keep the client anonymous ("Midwest precision machining company, $120M revenue"). Never name them in content.
2. Marketing angle I want us to push: "Pull Kanban + Monte Carlo beats forecast-push planning" — direct contrast against NetStock's approach. That's our displacement wedge.
3. For PE conversations, lead with working capital release: 21% of inventory value on a $120M manufacturer is real EBITDA-adjacent money. Perpetual license framing lands well there — no new recurring SaaS line on the P&L.

Also — next pilot candidates should be NetSuite shops first. SAP B1 integration took 3 weeks vs 1 week for NetSuite; let's not repeat that on a POC clock.

Narayan

---
**From:** Ashok Suthar <ashok@analytos.ai>
**To:** Narayan Laksham; Santosh Thota
**Subject:** RE: RE: Stockly pilot — 90-day numbers are in
**Date:** Mon, 15 Jun 2026 14:03

Noted. One more for the knowledge base: the supplier lead-time module found quoted vs actual lead time gaps averaging 9 days on the top 50 suppliers. That's feeding the sim now and is a great demo moment — buyers don't believe their own supplier data until they see it.

Ashok
