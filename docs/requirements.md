# Requirements — ha-enedis (`enedis_entreprise`)

## Use cases

- Business site with a meter > 36 kVA (segment C4, PME-PMI / Linky Pro…): electricity in the Energy
  dashboard and statistics, with the **5-minute load curve**.
- Check subscribed power against **max power reached** and **overruns** (R64 for > 36 kVA meters).
- Spot the night / holiday baseline ("talon") and abnormal peaks.
- Later (Hesto): several sites / PRM, several SIREN, same code.

## Configuration

- Config flow: choose the source (IMAP / local folder / SFTP), its settings, the AES key of the Enedis
  channel; optional PRM filter (default: all PRM found in files). Options: history import from a CSV
  export (one-off service), "no file received" alert delay (default 3 days).

## Data and entities (per PRM)

| Data | Source | In HA |
|---|---|---|
| Active power, 5-min points (W) | R63A `PA`, `CONS` | hourly energy statistic `enedis_entreprise:<prm>_energy` (kWh = Σ W × 5/60/1000), backfilled from files |
| Max of the curve per day (kW) | computed from R63A | statistic (max) + sensor "yesterday's peak" |
| Indexes per time class (Wh) | R64A `EA`, per `codeCadran` / class | sensors (last index per class), optional statistics per class |
| Max power reached (VA) | R64A `PMA` | sensor + statistic (max) |
| Overrun duration (s), overrun energy / quadratic (Wh) | R64A `DD`, `DE`, `DQ` | sensors; binary sensor "overrun yesterday" |
| Reactive energy / voltage | R63A `PRI`, `PRC`, `E` (when delivered) | optional, disabled by default |
| Last file received, last data timestamp, data nature counts (R/E/C/coupures) | | diagnostic sensors |

## Behaviour

- Poll the source every 30–60 min (files arrive "au fil de l'eau" every 2–24 h depending on the
  subscription); process each archive once (key: `codeFlux`+`idDemande`+`numSequence`).
- Points of nature `E` (estimated) / `C` (corrected) later replaced by better data → overwrite.
- Daylight-saving days handled (`H`/`P` natures, 23 h / 25 h days).
- Wrong key / undecryptable file → Repairs issue, file kept for retry after reconfiguration.
- No file for N days → Repairs issue (subscription stopped, channel broken).

## Acceptance (v0.1)

1. Synthetic R63A and R64A files (JSON and CSV, encrypted with a test key) produce the expected
   statistics and sensors; re-processing a file is a no-op (tests).
2. Daily kWh from R63A match `enedis_energie` (MCP connector) for the same days on the real account.
3. IMAP source picks up a new Enedis e-mail and ignores others; nothing is deleted or moved.
4. CI green (hassfest, HACS, ruff, mypy, pytest).
