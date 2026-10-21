# BijliCast demo video (2:47)

The submitted video is a screen recording of the live dashboard with an English (Indian accent) voiceover and
burned-in captions. It runs 2 min 47 s, inside the 3-minute limit.

- File: `build/demo_video/bijlicast_demo.mp4` (1920x1080, 30 fps, about 16 MB; not in git)
- Captions as a separate file, for YouTube: `build/demo_video/bijlicast_demo.srt`

## Timeline

| Time | On screen | Voiceover |
|---|---|---|
| 0:00-0:17 | Title card, then the cursor runs along the K-Electric November forecast | Every night in Karachi, millions of fans and air conditioners run together. K-Electric must decide in advance how much electricity to buy from the national grid, for every hour. Get it wrong, and it's load-shedding, or crores wasted. This is BijliCast. |
| 0:17-0:34 | Last-year line, the gap to this year, Peak Cost Lens, "Review flagged data" | The simple method is to copy last year's numbers. But Karachi's grid draw has jumped since 2025, prices rose sharply in the 2026 fuel crisis, and even the official files contain errors. Planners need a forecast they can trust, and check. |
| 0:34-0:48 | Data page: every source file with publisher, fetch time and SHA-256 | BijliCast uses only official data: ISMO's hourly demand for K-Electric and nine DISCOs, market prices, and ERA5 weather. Over four and a half lakh rows, every file fingerprinted. |
| 0:48-0:59 | Data quality tab, Decision log, FLAG filter, the copied-month rows | Our Data Quality Agent checks every file and decides: fix, fill, or flag, always with a written reason. It even caught ISMO re-uploading old months as new ones. |
| 0:59-1:11 | Workspace chart: line, 80% band, last year, evening window | Pick any company and month. The blue line is the hourly forecast, the shaded band is the eighty percent range, the dashed line is last year, and pink marks the evening peak-tariff window. |
| 1:11-1:18 | Outlook card, then hour 19 in Explore an hour | The outlook card gives the mean and the peak. Pick any hour, say 7 PM, and the chart follows instantly. |
| 1:18-1:27 | Peak Cost Lens, Model performance, Data confidence | Below: the Peak Cost Lens shows what each hour costs, then model accuracy, and Data Confidence: freshness, quality and drift. |
| 1:27-1:38 | Asks "Compare next month with last year"; row IDs and the K-Electric citation | Now let's ask BijliCast. Every number comes from our database with a row ID, and every recommendation cites an official source, here, K-Electric's own peak-hours page. |
| 1:38-1:44 | Asks "What is the electricity demand in Gilgit next month?" | And when there's no evidence, it doesn't make things up. It says: I don't know. |
| 1:44-1:49 | Switches the whole app to Urdu | Everything works in Urdu too, fully right to left. |
| 1:49-1:54 | Forecasts tab: all 10 companies | The Forecasts view covers all ten distribution companies at a glance. |
| 1:54-2:02 | Scenarios at +3 °C, then +5 °C with the outside-training-range warning | Scenarios asks: what if it's hotter? We show the full response, and flag when it goes beyond the temperatures the model has seen. |
| 2:02-2:14 | Analysis: overall and K-Electric error vs baseline | On months the model never saw, our error is thirteen point five percent, against eighteen percent for copying last year. For K-Electric: ten point one versus seventeen point three. |
| 2:14-2:22 | Errors by entity (IESCO, FESCO) and by season (summer) | And we're honest about weak spots: Islamabad and Faisalabad show no real gain, and very hot summer peaks are under-forecast. |
| 2:22-2:31 | Prefect: the hourly bijlicast-hourly runs | Everything refreshes every hour through a Prefect pipeline. If a quality check fails, it keeps the last good data instead of showing bad numbers. |
| 2:31-2:47 | End card: tech stack, live demo and code links | Built with Python, DuckDB, scikit-learn, FastAPI and Prefect, plus a multilingual RAG agent. BijliCast: honest, hourly power planning for Pakistan. Thank you! |

It covers what the participant guide asks the video to show: the problem, user and decision; data sources and
quality decisions; the dashboard; model vs baseline; one cited answer; one "I don't know"; results by group and
limits; and the impact for Pakistan. Every spoken number matches the dashboard and
[reports/model_report.md](../reports/model_report.md). It says "compared with the baseline", never "better than
K-Electric": K-Electric's own forecasts are not public.

## How it was made

- The app ran locally (`python run.py web`, Prefect on :4200). Headless Chrome, driven by Playwright, clicked
  through the screens on a fixed script while every repaint was captured, so it shows the real app with live data.
- The voiceover is synthetic: Microsoft Edge neural text-to-speech, voice `en-IN-NeerjaExpressiveNeural`, via
  `edge-tts`. Each scene's actions are timed to its line, and captions come from the speech word timings.
- ffmpeg joined the frames, voice and captions. Disclosed in [AI_Use_Log.md](../AI_Use_Log.md).
- The scripts that made it are in `build/demo_video/tools/` (not in git).

## Upload

- YouTube as **Unlisted** (upload `bijlicast_demo.srt` as subtitles if you like), or Google Drive with
  **Anyone with the link**.
- Open the link in a private window and check it plays without signing in, then paste it into the submission form.
