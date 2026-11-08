# M0 benchmark: results

> **Status: not run yet.** Needs the 5-minute test clip (plan Task 0, Step 5) and ~2 GB free disk for
> CPU PyTorch + model weights. Fill this in after Steps 1–3 of plan Task 13.

## Setup
- Machine: (laptop: 4 cores, 3.7 GB RAM, no GPU)
- Clip: (resolution, fps, length, camera height/position)

## Numbers
| | Plain | Tiled far half |
|---|---|---|
| ms/frame mean (p95) | | |
| Projected time, 90 min @ 10 fps, laptop | | |
| Estimated time on N100 pilot box (laptop × 0.6, an assumption) | | |
| Hand-checked: on-pitch players detected (10 frames) | | |
| Frames meeting ≥ 85% of players detected | / 10 | / 10 |
| Median track length (s) | | |
| Ball detected frame ratio (informational) | | |

Spec target: ≥ 85% of on-pitch players detected in ≥ 80% of sampled frames; 90-minute session ≤ 8 h on the pilot box.

## Verdict
GO / GO-with-tiling / NO-GO — recommended sample fps for Plan 2:

If NO-GO, bring this file to the owner before Plan 2. Options: higher camera position, RF-DETR Small, lower sample fps.
