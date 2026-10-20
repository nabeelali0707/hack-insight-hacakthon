# Business Model: BijliCast

Every rupee figure below comes from a gold table, and the row IDs are given. "Exposure" means
forecast mismatch (MWh) priced at ISMO's hourly system marginal price. It shows how much money is
**at risk** from planning to the wrong number. It is **not** a saving K-Electric would bank
automatically, because contracts, take-or-pay terms and dispatch rules decide how much of it can
actually be captured.

## 1. Who is the user?

- **Primary user:** the K-Electric (KE) demand-planning / power-procurement desk. They decide how much
  to draw from the national grid each hour of the coming month, versus KE's own plants, and when to
  run demand-response messaging.
- **Secondary users:** planning engineers at the 9 government-owned DISCOs; ISMO and NEPRA analysts;
  energy journalists and the public (Urdu briefs).

## 2. Who pays?

| Payer | Why they pay | Model |
|---|---|---|
| **K-Electric** (listed private utility) | Lower procurement risk on grid imports; evidence for NEPRA filings | Annual licence: API, alerts, custom retraining on KE's own feeder data |
| **DISCOs via the Power Division / donor programmes** | The CTBCM market requires DISCOs to forecast and contract their own demand | Contract or grant for a shared DISCO deployment |
| **Public (free tier)** | Transparency: Urdu briefs, data-quality status of public ISMO data | Free; funded by the paid tiers |

**Freemium:** the basic public dashboard and Urdu briefs are free. Planner-grade forecasts, alerts,
the API and retraining on private data are paid.

## 3. What is the value?

**One-sentence value proposition.** For **K-Electric's procurement planners**, who need to decide
**how much grid power to plan for each hour of next month**, BijliCast **forecasts KE's hourly grid
draw with uncertainty ranges and cited explanations**, so that **less money is at risk from
mis-planning, especially in the expensive evening peak**, unlike **today's practice of carrying
forward last year's numbers**, which is BijliCast's declared baseline.

| Value driver | Evidence from gold tables |
|---|---|
| Lower mismatch exposure on KE's grid draw | On the test months, the model cut KE's exposure from the baseline's level by an average of **Rs 83.9 million per average day** (`EC-KE-202601` … `EC-KE-202609`). The largest cuts were in the high-price months Apr and May 2026: Rs 175.5M and 184.4M/day (`EC-KE-202604`, `EC-KE-202605`). |
| Peak-shift opportunity | Moving 5% of KE's demand out of its 3 most expensive hours was worth **Rs 16–498 million per month** across Oct 2025–Sep 2026; Aug 2026 alone was Rs 497.7M (`PC-KE-202510` … `PC-KE-202609`). |
| Peak cost concentration | The evening peak (18–22 h) carries 22–31% of KE's daily grid cost (`PC-KE-*`), so a megawatt mis-planned at peak costs more than one off-peak. |
| Trust | Every number is traceable to a row ID; the Data Quality Agent caught copied months and stale values in the official ISMO files that a planner would otherwise use unknowingly. |

**Conservative framing for the jury.** If KE captured only **1%** of the exposure reduction above,
that is about Rs 0.84M per day, or **~Rs 306M per year** (0.01 × 83.9 × 365). The running cost below
is a tiny fraction of that.

## 4. How does it sustain itself?

1. **Licence** with KE: annual fee, priced well below 1% of the value above.
2. **DISCO deployment** funded through the Power Division's CTBCM readiness work or a donor energy
   programme.
3. **Free public tier** for awareness, plus the Urdu briefs for local media.

## 5. What does it cost to run? (monthly estimates, stated assumptions)

| Item | Estimate | Assumption / source |
|---|---|---|
| Compute: one small always-on VM (2 vCPU, 4 GB) for the hourly flow | ~US$20 | A full rebuild takes about 2 minutes; the hourly run re-downloads only 10 small weather files (optimization log OPT-10) |
| Dashboard hosting (Hugging Face Space, CPU basic) | US$0 | Free tier |
| Weather data | US$0 non-commercial; a paid Open-Meteo plan for commercial use | Open-Meteo's terms; price to be confirmed at contract time |
| ISMO / NEPRA data | US$0 | Public publications |
| Optional LLM wording (Claude) | ~US$60 if enabled for 144 briefs/day; US$0 with templates | Deterministic templates are the default |
| People: 0.25 FTE analyst | Largest cost | Approves review-queue decisions, monitors drift, retrains monthly |

## 6. Key assumptions

- ISMO's marginal price is a cost **indicator**, not KE's actual purchase price.
- KE's "demand" in ISMO data is its draw from the national grid, which is the quantity KE must plan for.
- Value scales with KE's grid dependence, which ISMO's data shows rising sharply since 2025 (drift row `DR-KE-LEVEL-202609`).

## 7. Biggest risks and mitigations

| Risk | Mitigation |
|---|---|
| ISMO changes or stops its public files (we already saw broken links and copied months) | Data Quality Agent flags them; Source Scout; plus a data-sharing MoU with KE for feeder-level data |
| Users don't trust a model | Every number is cited to a row ID; honest weak spots (IESCO/FESCO, summer extremes) are shown; human review queue |
| Model drift (KE's grid draw jumped in 2025) | Drift monitor; retraining is recommended but needs human approval |
| Wrong output causing harm | Planning information only; points users to KE 118 and NEPRA; never issues dispatch or load-shedding instructions |
