## Pooled ground truth (36 clusters, 18 true / 18 false)

Headline table. The 95% CI is a percentile bootstrap over clusters; p is a two-sided
permutation test against AUC = 0.5. An interval containing 0.500 means the method is
not distinguishable from chance on this ground truth.

| method | n | roc_auc | auc_ci | auc_p | pearson_r | separation | accuracy | f1 |
|---|---|---|---|---|---|---|---|---|
| B2 sensationalism lexicon | 36 | 0.7963 | [0.639, 0.931] | 0.0015 | 0.4505 | 9.13 | 0.6944 | 0.766 |
| B5 semantic fidelity only | 36 | 0.7191 | [0.548, 0.883] | 0.0215 | 0.377 | 6.72 | 0.6389 | 0.6977 |
| B3 TF-IDF overlap | 36 | 0.7052 | [0.525, 0.875] | 0.0335 | 0.357 | 8.43 | 0.6389 | 0.7234 |
| B6 claim substantiation (isitfake-style) | 36 | 0.6512 | [0.466, 0.830] | 0.135 | 0.2419 | 14.44 | 0.6111 | 0.72 |
| VeriNews TVS (3 factors) | 36 | 0.6404 | [0.446, 0.826] | 0.1545 | 0.2528 | 5.94 | 0.6667 | 0.5385 |
| B4 source count | 36 | 0.483 | [0.344, 0.623] | 0.73 | -0.1446 | -3.33 | 0.5 | 0.6667 |
| B1 source reputation (NewsGuard-style) | 36 | 0.4228 | [0.244, 0.622] | 0.433 | -0.1995 | -4.24 | 0.5 | 0.6667 |
| B7 evidence verdict (Justificat-style) | 36 | 0.3873 | [0.202, 0.594] | 0.2485 | -0.1291 | -3.27 | 0.5556 | 0.68 |

## Held-out split only (15 clusters)

| method | roc_auc | pearson_r | mean_true | mean_false | separation | accuracy | f1 |
|---|---|---|---|---|---|---|---|
| B1 source reputation (NewsGuard-style) | 0.8125 | 0.3442 | 36.83 | 29.94 | 6.89 | 0.8667 | 0.8571 |
| B2 sensationalism lexicon | 0.8036 | 0.4262 | 88.05 | 77.16 | 10.89 | 0.8 | 0.7692 |
| B3 TF-IDF overlap | 0.6786 | 0.3066 | 28.0 | 22.72 | 5.28 | 0.7333 | 0.7143 |
| B6 claim substantiation (isitfake-style) | 0.5714 | -0.0057 | 51.33 | 51.7 | -0.37 | 0.6667 | 0.7368 |
| B5 semantic fidelity only | 0.5179 | -0.0235 | 78.11 | 78.46 | -0.35 | 0.4667 | 0.6364 |
| B7 evidence verdict (Justificat-style) | 0.5 | -0.0653 | 33.2 | 35.15 | -1.95 | 0.5333 | 0.6316 |
| B4 source count | 0.4821 | -0.0877 | 90.71 | 93.0 | -2.29 | 0.4667 | 0.6364 |
| VeriNews TVS (3 factors) | 0.4375 | -0.0698 | 62.0 | 63.62 | -1.62 | 0.6 | 0.4 |

## Split stability

The same method evaluated on each half. Large swings show that a
single split of this size cannot rank methods, which is why the pooled table leads.

| method | AUC calibration | AUC held-out |
|---|---|---|
| B2 sensationalism lexicon | 0.7909 | 0.8036 |
| B5 semantic fidelity only | 0.8545 | 0.5179 |
| B3 TF-IDF overlap | 0.7045 | 0.6786 |
| B6 claim substantiation (isitfake-style) | 0.7455 | 0.5714 |
| VeriNews TVS (3 factors) | 0.7682 | 0.4375 |
| B4 source count | 0.4909 | 0.4821 |
| B1 source reputation (NewsGuard-style) | 0.1591 | 0.8125 |
| B7 evidence verdict (Justificat-style) | 0.3864 | 0.5 |
