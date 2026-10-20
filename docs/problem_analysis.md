# Problem Analysis: BijliCast — Karachi & DISCO Hourly Demand Intelligence

Track: **Energy demand** · Team: *(fill in)* · HackInsight '26

## 1. Primary user and the decision

**Primary user:** the demand-planning / power-procurement desk at **K-Electric (KE)**, Karachi's vertically integrated utility.

**Decision:** for each hour of the coming month, how much electricity to plan for, how much to draw from the national grid versus its own plants, and which hours need load-management or demand-response messaging.

**Secondary users:**
- DISCO planning engineers (LESCO, FESCO, …) making the same decision for their regions.
- Analysts at ISMO / NEPRA who monitor market demand.

## 2. The problem, with evidence

- Pakistan moved to a **Competitive Trading Bilateral Contract Market (CTBCM)** run by the Independent System and Market Operator (ISMO). Under it, distribution companies must forecast and contract their own demand. ISMO now publishes hourly marginal prices and DISCO-level hourly demand profiles (ISMO Dashboard, <https://www.ismo.gov.pk/dashboard>).
- ISMO notes that since **Feb 2026**, Middle East fuel-supply disruptions have pushed **marginal prices above their usual range**. That makes every mis-forecast evening-peak megawatt more expensive (ISMO, *Hourly Marginal Price Data* tab).
- K-Electric used **13.3% of all energy consumed by DISCOs** in Sep 2026 (ISMO, *DISCOs Consumption Sep 2026*). Karachi has repeated gas-shortage-related outages, and KE meets part of its peak by importing from the national grid (Dawn, <https://www.dawn.com/news/2036015>).
- Accurate 1–15 day load forecasts help a utility choose the **cheapest mix of power plants**. This was the winning idea of the LUMS team in K-Electric's own 7/11+ Innovation Challenge (<https://lums.edu.pk/news/lums-wins-kes-711-innovation-challenge>), but no open, reproducible version exists.

## 3. Who is affected, and where

| Group | Why it matters |
|---|---|
| Karachi households and industry (KE territory, Sindh) | Mis-planned peaks lead to load-shedding and higher fuel-cost adjustments on bills. |
| Other provinces' DISCO customers (Punjab, KP, Balochistan, rest of Sindh) | Same mechanism, with different climate and losses. QESCO, SEPCO and PESCO have very different load shapes from LESCO. |
| Time-of-day | The **evening peak (18:00–22:59)** is the most expensive and most error-prone period. |
| Season | Summer cooling load (May–Sep) drives the annual peak; winter demand is far lower. |

These groups are the slices we will check for unequal model errors.

## 4. Outcome we predict

**Average demand (MW) for each hour of the day (0–23, PKT), for each entity, for each month.**
- Entities: K-Electric plus nine DISCOs.
- Frequency: monthly profile (24 numbers per entity per month).
- Unit: MW (= MWh per hour).
- Source: ISMO monthly publications, Feb 2023 – Sep 2026.

## 5. Baseline and success measure

See [`baseline_declaration.md`](baseline_declaration.md).
- **Baseline:** seasonal naive, i.e. the same month last year at the same hour.
- **Success:** the model's test MAPE is at least 10% lower than the baseline's, and K-Electric's error is also lower.

## 6. Limits and risks

- **Monthly averages, not individual days.** We forecast the typical hourly shape of a month, not tomorrow's exact peak. ISMO does not publish day-by-day DISCO demand.
- **Served demand is not true demand.** When load is shed, recorded demand is lower than what customers wanted. Our forecasts inherit that suppression.
- **Publication delay.** ISMO publishes each month about 15 days after it ends, so the model may only use demand that is at least 2 months old.
- **Invisible rooftop solar.** Behind-the-meter solar lowers daytime grid demand. We only see it indirectly, through solar radiation and trend features.
- **Weather is a single grid cell per DISCO** (the DISCO's headquarters city, from ERA5 / Open-Meteo), not a service-area average.
- **Gaps in history.** ISMO's DISCO files start in Feb 2023, and several months are missing (e.g. Mar–Aug 2023). The Data Quality Agent flags these.

## 7. Recommendation and what we do not claim

BijliCast is **planning information**. It is not an operational dispatch tool and not an official ISMO or NEPRA forecast.
- Every number shown comes from a gold table with a row ID.
- Every recommendation cites a published document.
- For official schedules, tariffs or load-shedding plans, users should go to K-Electric (118 helpline, ke.com.pk), ISMO or NEPRA.
