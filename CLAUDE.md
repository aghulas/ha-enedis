# ha-enedis — Home Assistant integration for Enedis business recurring publications (R63 / R64)

Guide for Claude Code sessions on this repo. Goal: import into HA long-term statistics and the Energy
dashboard the electricity data that **Enedis pushes** to a business customer through its *publications
récurrentes* (flux R6X): R63 load curve (5-min steps for meters > 36 kVA) and R64 indexes (per time
class, plus max power reached and overrun data). **No login to the Enedis portal, no captcha, no
password to Enedis** — the integration only reads files Enedis already sent.

## Why this design

The Enedis business portal is protected by a captcha that refuses automated browsers: the MCP connector
(`~/dev/enedis-mcp`) needs the user to log in in a real Chrome, which HA (headless) cannot do. API access
(Data Connect / business APIs) requires a contract or a habilitation the user does not have. The
recurring publications, set up once in the business account, deliver encrypted zip files by **e-mail or
FTP** — fully automatable and local.

## Delivery channel (configurable "source" of files)

1. **IMAP mailbox** (first target): a dedicated mailbox receives Enedis e-mails with the zip attached;
   the integration reads new messages, never deletes or moves them by default (track processed files).
2. **Local folder** (`/share/...`, `/media/...`) fed by anything else (FTP server elsewhere, manual drop).
3. **SFTP/FTPS pull** from an external host (e.g. a web-hosting FTP account) — so no port is ever opened
   on the site's network. **Never** run an FTP server exposed to the Internet on the HA host from this
   integration (it drives heating equipment); document that in the README.

## Non-negotiable rules

1. **Read-only** towards Enedis and the mailbox (no delete/move unless the user opts in explicitly).
2. **Secrets**: AES decryption key, IMAP/SFTP passwords → config entry only, redacted in diagnostics,
   never logged; PRM (14 digits), SIREN, names, addresses → never in logs, fixtures or the repo.
   Fixtures are synthetic, built from the format described in `docs/api.md`. No school-specific data.
3. **Idempotent statistics** with real timestamps; a file processed twice changes nothing; late
   corrections (BEST data) overwrite previous values for the same period.
4. **Robust parsing**: unknown flux codes or fields → warning + skip, never crash the coordinator.

## Reuse

- `~/dev/enedis-mcp/` (private): PRM handling, 5-min curve aggregation (`modeles.py`), CSV export of the
  portal history (`enedis_courbe_charge(..., export_csv=True)`) — usable for a **one-off history import**
  service in this integration (R6X only delivers from the subscription date onwards).
- `~/dev/enedis-mcp/skills/courbe-charge-enedis/SKILL.md` — semantics (talon, peaks, subscribed power).
- `~/dev/ha-danfoss-ally` — layout, CI, conventions.

## Prerequisite on the user side (blocking for real tests)

The user must, as administrator of the Enedis business account: create the R63 (load curve, BEST,
daily, JSON) and R64 (index, daily, JSON) subscriptions; after the 72 h activation delay, create the
e-mail channel and get its decryption key. Until the first real file arrives, build against synthetic
fixtures; then calibrate on the real file (kept **outside** the repo, `samples/real/` is git-ignored).

## Progress

- Session 1 done: `api/decrypt.py`, `api/r6x.py`, `docs/api.md` (the decryption note is now
  **Enedis-MOP-CF_080E**, same content and URL as NOI-CF_107E). Open questions: end of `docs/api.md`.
- Session 2 done: `sources/` (folder, IMAP read-only, FTPS — **SFTP not done**, it needs a dependency),
  `energy.py` + `stats.py` (hourly statistics, 60-day point buffer for split hours and corrections),
  `coordinator.py` (state persisted in a `Store`). `config_flow.py` is a placeholder that aborts.
- Tests that use `hass` must request `recorder_mock` (the integration depends on `recorder`).

## Suggested sessions

1. Read `docs/api.md`; download and read Enedis note **Enedis-NOI-CF_107E** (decryption of files sent
   on digital channels) and the R6X guide; complete `docs/api.md` (exact AES mode, IV, key format,
   padding) and write `api/decrypt.py` + `api/r6x.py` (parsers R63A/R64A, JSON and CSV) with tests.
2. Sources (IMAP, folder, SFTP), processed-file store, coordinator, statistics import.
3. Config flow (source + key), diagnostics, Repairs (key wrong, no file for 3 days), CI.
4. Real file from the user → calibration → manual test on HA.
