# Stockly — Product Overview (Internal)

**Product site:** stockly.analytos.ai
**Category:** Pull Kanban inventory intelligence for discrete manufacturing
**Owner:** Analytos Labs product team
**Status:** In production with pilot customers

## What Stockly Does

Stockly replaces manual kanban cards and replenishment spreadsheets with an AI-driven Pull Kanban engine. It continuously right-sizes kanban loops and safety stock so plants stop carrying excess inventory without risking stockouts.

## Core Features

1. **Pull Kanban engine** — digital kanban loops per SKU/work-center, automatic card sizing and re-sizing as demand shifts.
2. **Monte Carlo safety-stock simulation** — runs 10,000 demand/lead-time scenarios per SKU nightly to recommend optimal safety stock, instead of static min/max rules.
3. **Demand-shift detection** — flags SKUs whose consumption pattern changed (seasonality, new customer, phase-out) and proposes loop adjustments with human approval.
4. **ERP integration** — native connectors for NetSuite and SAP Business One; reads item masters, open POs, consumption; writes recommended reorder signals.
5. **Autonomy tiers** — Tier 1 recommend-only, Tier 2 auto-adjust with approval, Tier 3 fully autonomous replenishment signals; every agent action is logged separately from human actions in the activity log.
6. **Supplier lead-time intelligence** — learns actual vs. quoted lead times per supplier and feeds the simulation.

## Proof Points (approved for external use)

- Pilot at a Midwest precision machining company ($120M revenue, ~3,400 active SKUs on kanban): **21% reduction in on-hand inventory value** and **35% fewer stockout events** within 90 days.
- Inventory planner time on replenishment reviews cut from **6 hours/week to under 1 hour/week**.
- Typical deployment: **2-week POC, 90 days to full production** (standard Analytos model).

## Competitive Positioning

Primary displacement target: **NetStock** and spreadsheet-based min/max planning. Stockly wins on Pull Kanban methodology (vs. forecast-push), Monte Carlo simulation depth, agentic autonomy tiers, and on-premises perpetual licensing option (no forced SaaS subscription — important for PE-owned plants sensitive to recurring cost).

## Technical Stack (internal only)

React front-end, Flask API, PostgreSQL, AWS. AI layer currently GPT-4.1 mini for reasoning/explanations; Monte Carlo engine is deterministic Python (not LLM).

## Target Buyer

Plant Managers and Supply Chain Directors at mid-market discrete manufacturers; economic buyer often the CFO or PE operating partner. See ICP doc for full segmentation.
