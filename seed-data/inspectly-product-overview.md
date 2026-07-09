# Inspectly — Product Overview (Internal)

**Product site:** inspectly.analytos.ai
**Category:** Engineering drawing → inspection plan automation
**Owner:** Analytos Labs product team
**Status:** In production with a medical device manufacturing customer

## What Inspectly Does

Inspectly reads engineering drawings (PDF/TIFF) and automatically generates ballooned inspection plan workbooks in Excel — the documents quality engineers otherwise build by hand for every part revision. It extracts dimensions, tolerances, and GD&T callouts and maps them to inspection characteristics with measurement methods.

## Core Features

1. **Automated dimension extraction** — vision model reads drawings and extracts dimensions, tolerances, GD&T symbols, notes, and title-block metadata.
2. **Balloon numbering** — auto-balloons each characteristic on the drawing and keeps balloon numbers consistent across revisions.
3. **Excel inspection plan generation** — outputs the customer's own inspection plan template (characteristic #, nominal, tolerance, method, gauge) ready for FAI/PPAP packages.
4. **Revision diffing** — compares drawing rev B vs rev A and highlights changed characteristics only, so quality teams re-inspect what changed.
5. **Human verification step** — every extracted plan goes to a quality engineer for review before release; corrections feed back to improve extraction.

## Proof Points (approved for external use — client name NOT approved, refer to "a leading medical device manufacturer")

- At a leading medical device manufacturer: inspection plan creation time reduced from **4–6 hours per part to under 20 minutes**.
- **92% first-pass dimension extraction accuracy** across the initial four production part numbers processed; remaining 8% caught in the human verification step.
- Supports **ISO 13485 and AS9100** quality documentation contexts.

## Competitive Positioning

Alternatives are manual ballooning, or legacy tools like InspectionXpert that still require heavy manual cleanup. Inspectly differentiates on end-to-end automation with a built-in human verification loop and revision-aware diffing.

## Technical Stack (internal only)

Gemini Flash-class vision models for extraction; Python pipeline; Excel generation via openpyxl; deployed per-client (on-prem friendly).

## Target Buyer

Quality Managers and Quality Engineers at regulated discrete manufacturers (medical device, aerospace suppliers, precision machining). Economic buyer: Director of Quality or VP Operations. See ICP doc.
