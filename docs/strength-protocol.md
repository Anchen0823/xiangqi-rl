# Strength acceptance protocol

All matches use deterministic opening suites, color reversal, identical node limits where required, fixed hashes and archived PGNs/UCCI logs. Failed candidates never overwrite the champion manifest.

1. Play 800 games against the club baseline. The lower bound of the two-sided 95% Wilson confidence interval must exceed 60%.
2. Play 400 equal-node games against a strong CC0 teacher. The lower confidence bound must be at least 20%.
3. Score at least 90% on the versioned tactical suite.
4. Before claiming a human 1800–2000 level, play at least 20 offline games against verified club players and score above 50%.

Reports record engine commits, network SHA-256, hardware, clocks, command lines, adjudication settings and raw results. Release automation must reject an absent or failing report.
