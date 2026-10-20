# BijliCast ⚡ — Karachi & DISCO Hourly Demand Intelligence

HackInsight '26 · Data-to-Decision · **Energy demand track**

BijliCast forecasts the **hourly electricity demand profile of K-Electric (Karachi)** and Pakistan's nine other distribution companies (DISCOs). It is built only from official Pakistani data:

- **ISMO** monthly DISCO and K-Electric hourly demand files
- **ISMO** hourly marginal prices
- **ERA5** weather for each DISCO's headquarters city

A Data Quality Agent audits every file. A cited Insight Agent then explains the forecast in English and Urdu, using only numbers from the gold tables.

> Status: under active development during the hackathon. See [docs/problem_analysis.md](docs/problem_analysis.md) and the [baseline declaration](docs/baseline_declaration.md).

## Repository layout

| Path | What it holds |
|---|---|
| `config/sources.yaml` | Every source, URL and licence |
| `manifest.csv` | Every raw file: source, query, fetch time, SHA-256, licence |
| `src/bijlicast/` | Pipeline code: fetch → warehouse → quality agent → model → insight agent |
| `docs/` | Problem analysis, baseline declaration, dataset proposal, business model, optimisation log |
| `AI_Use_Log.md` | Disclosure of AI assistance |
