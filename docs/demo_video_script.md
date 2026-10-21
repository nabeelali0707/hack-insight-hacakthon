# BijliCast demo video script (3:00)

For whoever records the video. Length: about 400 words of voiceover at roughly 135 words a minute, so there is
room to speak with energy without rushing. Tone: clear, warm and enthusiastic. Speak slightly slower than feels
natural and pause for half a second at every screen change.

## Setup (2 minutes, before recording)

1. Start the app (`python run.py web`) and open **two Chrome tabs**:
   - Tab 1: `http://127.0.0.1:8000/#/workspace`
   - Tab 2: `http://127.0.0.1:4200/runs` (Prefect)
2. In Tab 1 select **K-Electric**, **November 2026**, language **EN**. Set browser zoom to **90%**.
3. Ask the assistant any question once, then refresh. The first answer loads the embedding model (about 10 s).
4. Close other tabs and notifications. Recorder: **Windows + Alt + R** (Xbox Game Bar), or OBS.

Backup: the public page `https://nabeelali0960-bijlicast.static.hf.space` works too. Both questions in the script
are among its prepared answers (pick them from the suggestions), but it has no Prefect tab, so show
`reports/prefect_dashboard.png` at 2:30 instead.

## Script

| Time | Chrome action | Voiceover (say exactly) |
|---|---|---|
| **0:00-0:15** Hook | Workspace, top of page. Slowly hover across the evening (pink) zone of the chart. | "Every evening in Karachi, millions of ACs switch on together. K-Electric must decide in advance how much electricity to buy from the national grid, for every single hour. Get it wrong, and it's load-shedding or crores wasted. This is **BijliCast**." |
| **0:15-0:35** Problem | Stay on the Workspace. Hover the dashed "last year" line. | "Today, the simple method is to copy last year's numbers. But Karachi's grid draw has jumped since 2025, prices rose sharply in the 2026 fuel crisis, and even the official government files contain errors. Planners need a forecast they can trust, and check." |
| **0:35-0:45** Data | Click **Data** in the left rail. Scroll the file list slowly. | "BijliCast uses only official Pakistani data: ISMO's hourly demand for K-Electric and nine DISCOs, hourly market prices, and ERA5 weather. That's over four and a half lakh rows, every file fingerprinted." |
| **0:45-0:57** Data Quality Agent | Click **Home**, then the **Data quality** tab. Scroll to **Decision log** and click the **FLAG** chip. | "Our Data Quality Agent checks every file and decides: fix, fill, or flag, always with a reason. It even caught ISMO re-uploading old months as new ones." |
| **0:57-1:10** Forecast chart | Click the **Workspace** tab. Hover the blue line, the band, then the pink zone. | "On the Workspace, pick any company and month. The blue line is the forecast for each hour, the shaded band is the eighty percent range, the dashed line is last year, and pink marks the evening peak." |
| **1:10-1:18** Outlook and hour | Point at the blue **November outlook** card, then click hour **19** in **Explore an hour**. | "The outlook card gives the mean and the peak. Pick any hour, say 7 PM, and the chart follows instantly." |
| **1:18-1:28** Cards | Scroll down to the three cards. Hover each briefly. | "Below: the Peak Cost Lens shows what each hour costs, then model performance, and Data Confidence: freshness, quality and drift, all live." |
| **1:28-1:45** Cited answer | Type in **Ask BijliCast**: `Compare next month with last year` and press Enter. When the drawer opens, scroll to **Document sources**. | "Now let's ask BijliCast. Every number comes straight from our database with a row ID, and every recommendation cites an official source. Here, it's K-Electric's own peak-hours page." |
| **1:45-1:55** "I don't know" | In the drawer type: `What is the electricity demand in Gilgit next month?` and press Enter. | "And when there's no evidence, it doesn't make things up. It honestly says: I don't know." |
| **1:55-2:03** Urdu | Close the drawer. Click **اردو** (top right), pause for 2 seconds, then click **EN**. | "Everything works in Urdu too, fully right-to-left." |
| **2:03-2:10** All companies | Click the **Forecasts** tab. Scroll the 10 cards once. | "The Forecasts view covers all ten distribution companies at a glance." |
| **2:10-2:20** Scenarios | Click **Scenarios** in the rail, then **+3°C**. Hover the response table. | "Scenarios asks: what if it's three degrees hotter? We show the full response, and we clearly flag where the model is less reliable." |
| **2:20-2:30** Honest limits | Click **Analysis**. Scroll to **Errors by entity**. Hover IESCO and FESCO. | "And we're honest about weak spots. Islamabad and Faisalabad don't beat the baseline, and very hot summer peaks are under-forecast." |
| **2:30-2:42** Automation | Switch to the **Prefect** tab and show the list of completed runs. | "All of this refreshes every hour through a Prefect pipeline. If a quality check fails, it keeps the last good data instead of showing bad numbers." |
| **2:42-2:52** Results | Switch back. Click **Analysis** and point at the top tiles. | "On months the model never saw, our error is thirteen point five percent, against eighteen percent for last year's numbers. For K-Electric: ten point one versus seventeen point three." |
| **2:52-3:00** Outro | Click **Home**. Show the public link `nabeelali0960-bijlicast.static.hf.space` in the address bar or as a caption. | "Built with Python, DuckDB, scikit-learn and a multilingual RAG agent. BijliCast: honest, hourly power planning for Pakistan. Thank you!" |

## What the video covers

Problem and user, data sources and quality decisions, the dashboard, model vs the declared baseline, one cited
answer, one "I don't know", Urdu, results by group and limits, the hourly Prefect pipeline, and Pakistani impact.

Say "compared with the baseline", never "better than K-Electric": K-Electric's own forecasts are not public.

## If it runs long

Cut the **Forecasts** row (2:03-2:10) first; it is the least critical.

## Upload

- Record voice and screen together, or record the voice separately and lay it over the screen recording in
  Clipchamp (free on Windows 11).
- Upload to YouTube as **Unlisted**, or to Google Drive with **Anyone with the link**.
- Open the link in a private window and check it plays without signing in, then paste it into the submission form.
