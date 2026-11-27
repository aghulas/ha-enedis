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

Subscriptions were created on 2026-11-18, all JSON: index daily, raw load curve daily, corrected load
curve weekly (the account offers no daily corrected curve — see `docs/api.md`). An e-mail channel
already exists in the account; the three subscriptions were linked to it on 2026-11-21. Still to do by
the user: copy the channel's decryption key into the integration (never into the repo) once the
e-mails arrive. First real files (downloaded from the account, plain zips) are in
`samples/real/2026-11-21/`; what they showed is in `docs/api.md` ("Seen on the first real files"). Until the first real file arrives, build against synthetic
fixtures; then calibrate on the real file (kept **outside** the repo, `samples/real/` is git-ignored).

## Progress

- Session 1 done: `api/decrypt.py`, `api/r6x.py`, `docs/api.md` (the decryption note is now
  **Enedis-MOP-CF_080E**, same content and URL as NOI-CF_107E). Open questions: end of `docs/api.md`.
- Session 2 done: `sources/` (folder, IMAP read-only, FTPS — **SFTP not done**, it needs a dependency),
  `energy.py` + `stats.py` (hourly statistics, 60-day point buffer for split hours and corrections),
  `coordinator.py` (state persisted in a `Store`).
- Session 3 done: `config_flow.py` (menu → folder / imap / ftps, reconfigure keeps secrets left empty,
  options: PRM filter, no-file delay), `sensor.py` (status + one sensor per R64 index series),
  `diagnostics.py` (secrets redacted, PRM numbered), Repairs issues `undecryptable` and `no_file`
  (raised from the coordinator).
- Then: `sources/sftp.py` (paramiko, host key pinned at first contact), `api/history.py` + action
  `import_history` (CSV `debut;kw_moyen` from enedis-mcp), sensor "peak of the last complete day".
  **Not done on purpose**: "overrun yesterday" binary sensor — the meaning of the R64 `DD` values
  (cumulative? reset monthly?) must be read on a real file first.
- Installed on the school's Home Assistant (2026.11) through the Marketplace (ex-HACS) on 2026-11-18,
  folder source `/media`, no key yet. History import is also an options-flow step with a file upload
  (`file_upload` dependency): the media browser refuses CSV files, so that is how a file reaches HA.
- Calibration on the first real files (2026-11-21): archive names differ from the guide
  (`parse_filename` now accepts both); content parsed as is; a full local run gave 24 hourly rows for
  the day. Still open: e-mail attachment (encrypted?), sender/subject for IMAP, `DD` semantics, kWh
  check against the portal.
- Tests that use `hass` must request `recorder_mock` (the integration depends on `recorder`).
- Publication (2026-11-27): version 0.1.0, `CHANGELOG.md` (English, newest first — add an entry with
  every version bump), brand images in `custom_components/enedis_entreprise/brand/` (original
  artwork, never the Enedis logo), HACS action without `ignore`, `hacs.json` with `country: FR` and
  minimum Home Assistant 2025.1 (what the Python 3.12 CI job installs; the 3.14 job runs the current
  release, without mypy). Submission to `hacs/default` waits for a real encrypted e-mail to be read.

## Suggested sessions

1. Read `docs/api.md`; download and read Enedis note **Enedis-NOI-CF_107E** (decryption of files sent
   on digital channels) and the R6X guide; complete `docs/api.md` (exact AES mode, IV, key format,
   padding) and write `api/decrypt.py` + `api/r6x.py` (parsers R63A/R64A, JSON and CSV) with tests.
2. Sources (IMAP, folder, SFTP), processed-file store, coordinator, statistics import.
3. Config flow (source + key), diagnostics, Repairs (key wrong, no file for 3 days), CI.
4. Real file from the user → calibration → manual test on HA.
