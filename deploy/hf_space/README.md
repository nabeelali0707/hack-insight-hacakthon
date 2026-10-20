---
title: BijliCast
emoji: ⚡
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Hourly demand outlook for K-Electric and Pakistan's DISCOs
---

# BijliCast ⚡

Hourly electricity demand outlook for **K-Electric (Karachi)** and Pakistan's nine other distribution
companies. HackInsight '26, Energy demand track.

- **Data:** ISMO (Government of Pakistan) DISCO and K-Electric hourly demand profiles and hourly marginal
  prices; ERA5 / Open-Meteo weather; NEPRA, ISMO and K-Electric documents.
- **Data Quality Agent:** fix / fill / flag decisions, each logged with a reason.
- **Forecast model:** beats the pre-declared baseline (test MAPE 13.5% vs 18.0%) and shows 80% ranges.
- **Insight Agent:** answers in English and اردو, with row IDs and document citations; says "I don't know"
  when unsupported.
- **Pipeline:** refreshes every hour inside this Space. The dashboard shows data freshness, quality status
  and the last successful run.

Source code: https://github.com/nabeelali0707/hack-insight-hacakthon

Outputs are planning information, not an official ISMO/NEPRA forecast or dispatch instruction.
