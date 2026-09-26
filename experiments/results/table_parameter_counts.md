Calibration split: **11 true / 10 false** claims (fact-checker verdicts), decision threshold = 75.

| Family | Variant | Predicted true | Predicted false | Correct | Accuracy | F1 | Pearson r |
|---|---|---|---|---|---|---|---|
| semantic scale (base/range) | 0/100 | 4 | 17 | 14/21 | 0.6667 | 0.5333 | 0.5206 |
| semantic scale (base/range) | 20/80 | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.4963 |
| semantic scale (base/range) | 30/70 **(chosen)** | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.4731 |
| semantic scale (base/range) | 50/50 | 6 | 15 | 16/21 | 0.7619 | 0.7059 | 0.4023 |
| top-k sources | top-1 | 6 | 15 | 14/21 | 0.6667 | 0.5882 | 0.3005 |
| top-k sources | top-3 **(chosen)** | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.4731 |
| top-k sources | top-5 | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.5883 |
| top-k sources | top-all | 3 | 18 | 13/21 | 0.619 | 0.4286 | 0.6397 |
| domain ladder | flat | 7 | 14 | 15/21 | 0.7143 | 0.6667 | 0.6379 |
| domain ladder | mild | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.6003 |
| domain ladder | current **(chosen)** | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.4731 |
| domain ladder | steep | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.3437 |
| coherence mapping (base/range) | 0.50/0.50 | 4 | 17 | 14/21 | 0.6667 | 0.5333 | 0.5274 |
| coherence mapping (base/range) | 0.70/0.30 **(chosen)** | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.4731 |
| coherence mapping (base/range) | 0.90/0.10 | 8 | 13 | 16/21 | 0.7619 | 0.7368 | 0.4029 |
| coherence mapping (base/range) | 1.00/0.00 | 12 | 9 | 14/21 | 0.6667 | 0.6957 | 0.3497 |
| flag threshold | 60 | 14 | 7 | 12/21 | 0.5714 | 0.64 | 0.4731 |
| flag threshold | 70 | 7 | 14 | 15/21 | 0.7143 | 0.6667 | 0.4731 |
| flag threshold | 75 **(chosen)** | 5 | 16 | 15/21 | 0.7143 | 0.625 | 0.4731 |
| flag threshold | 85 | 1 | 20 | 11/21 | 0.5238 | 0.1667 | 0.4731 |
