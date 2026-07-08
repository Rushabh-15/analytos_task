<!-- SAMPLE STAND-IN. Replace this file with the real seed-data/icp-analytos.md
     provided in the task pack before your final run. -->

# Analytos — Ideal Customer Profiles

## Segment 1: Mid-market grocery & convenience retail (Stockly)

US and UK grocery, convenience and specialty-food chains, **30–400 stores**,
revenue $50M–$1.5B. High perishables mix (>25% of revenue), thin margins,
no in-house data-science team. Tech signals: modern cloud POS (NCR, Toshiba,
Square for Retail), spreadsheets or legacy demand planner for ordering.

**Trigger signals:** new VP Supply Chain hired; shrink flagged in earnings or
board decks; fresh/prepared-foods expansion; supplier consolidation project;
ESG or food-waste reporting commitments.

**Pain points:** produce waste, chronic stockouts on top movers, store
managers spending mornings on manual ordering, markdown decisions made by
gut feel.

**Disqualifiers:** fewer than 10 stores; franchise models where stores order
independently; chains mid-way through a full ERP re-platform.

### Personas

- **VP Supply Chain / Merchandising** — economic buyer. Goals: cut shrink,
  raise availability, defend margin. Objections: "another forecasting tool",
  integration effort, trust in AI-generated orders.
- **Store Operations Manager** — end user. Goals: shorter ordering routine,
  fewer emergency orders. Objections: change fatigue, tablet-in-hand
  workflow disruption.
- **Head of Data / IT** — influencer. Goals: no new ERP project, clean
  security review. Objections: data-sharing scope, SSO requirements.

## Segment 2: Regulated manufacturing & med-device QA (Inspectly)

European and North American medical-device, pharma-packaging and precision
manufacturers, **200–5,000 employees**, ISO 13485 / FDA 21 CFR 820 regimes.
Tech signals: eQMS in place (or Excel-based QC records), tablets on the
floor, recent audit findings on documentation.

**Trigger signals:** failed or "with observations" audit; new Head of
Quality; CAPA backlog growth; expansion of incoming-inspection volume; new
product line entering validation.

**Pain points:** inspection bottlenecks, inconsistent records across
inspectors, audit-prep fire drills, defects escaping to the field.

**Disqualifiers:** job shops under 100 employees; sites with no tablets or
banned cameras on the floor.

### Personas

- **Head of Quality / Regulatory Affairs** — economic buyer. Goals: pass
  audits with zero majors, cut cost of quality. Objections: validation
  burden for new software (CSV), data residency.
- **Field / Line Inspection Lead** — champion. Goals: less paperwork, faster
  shifts, defensible records. Objections: camera reliability, glove-friendly
  UX.
- **Plant Manager** — influencer. Goals: throughput, fewer re-inspections.
  Objections: line downtime during rollout.

## Competitive landscape

- Stockly vs **ForecastIQ** (warehouse-level forecasts, ignores expiry) and
  **ShelfSense** (shelf cameras only, no replenishment) — displacement angle:
  perishables-first modeling, live in weeks not quarters.
- Inspectly vs **AuditTrail Pro** (document control, no vision) and
  **ClipboardX** (checklist digitizer, non-compliant free-text records) —
  displacement angle: defect detection plus regulator-ready records in one.
