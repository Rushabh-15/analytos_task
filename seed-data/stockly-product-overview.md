<!-- SAMPLE STAND-IN. Replace this file with the real seed-data/stockly-product-overview.md
     provided in the task pack before your final run. Structure and metric style mirror
     what the pipeline expects; fixtures/ contains the matching extraction fixture. -->

# Stockly — Product Overview

**Tagline:** Demand forecasting and auto-replenishment for perishable retail.

Stockly is Analytos' AI inventory copilot for grocery and convenience retail.
It ingests POS transactions, supplier lead times, weather and local-event
signals, then produces SKU-store level demand forecasts and automatically
drafts purchase orders that a category manager approves in one click.

**Category:** Retail inventory optimization · **Stage:** live ·
**Website:** https://analytos.ai/stockly

## Core features

- **Perishable-aware forecasting.** Shelf-life decay curves per SKU; the model
  optimizes for sell-through before expiry, not just stock availability. This
  is our primary differentiator versus generic demand planners.
- **One-click replenishment.** Draft POs generated nightly per store with
  supplier constraints (MOQs, delivery windows) already applied.
- **Markdown optimizer.** Suggests dynamic discount timing for items
  approaching expiry to recover margin instead of writing off waste.
- **Shrink analytics.** Attributes waste to root causes (over-ordering,
  delivery variance, planogram gaps) with store-level league tables.

## Proof points

From a 12-week pilot with a mid-market US grocery chain (12 stores):

- Fresh-produce waste down **38%** over the 12-week pilot.
- Forecast error (WMAPE) improved from **41% to 22%** at SKU-store level.
- Store teams saved **9.4 hours per week** on manual ordering.
- Stockout rate on top-200 SKUs fell **27%**.

Internal benchmarks: typical deployment onboards in **under 2 weeks** because
Stockly reads standard POS exports (no ERP integration required for phase 1).

## Competitive context

Legacy demand planners (ForecastIQ, ShelfSense) forecast at warehouse level
and ignore expiry dynamics; Stockly wins deals on perishables-first modeling
and speed-to-value for mid-market chains that lack data-science teams.
