# Changelog

## 0.1.0 — 2026-11-27

First public release. **Beta**: read the "Limits" section of the README before relying on the figures.

- **Enedis recurring publications read**: R63 load curve and R64 indexes, JSON and CSV, from the
  archives Enedis publishes. Files sent on a contact channel are decrypted with the channel's key
  (AES-256-CBC, as described in Enedis' note); plain archives downloaded from the business account are
  read as they are. Archive names as actually published (`ENEDIS_R63A_…`, `ENEDIS_R64A_…_INDEX_…`) and
  as described in the guide are both recognised.
- **SFTP as the reference source**: Enedis deposits the files on a server outside your site, and Home
  Assistant collects them there with an outgoing connection (host key recorded at setup, refused if
  it changes later). A local folder and FTPS (explicit TLS only) are supported too. Nothing is ever
  deleted or moved on the server; each file is processed once.
- **No mailbox source**: the IMAP source of the development versions is removed. An entry that still
  uses it is not loaded and raises a repair issue asking to add the integration again with another
  source; statistics already imported are kept.
- **Statistics** for the Energy dashboard: hourly energy (kWh) and power (mean, min, max in kW) per
  meter, dated at their real time. Processing a file twice changes nothing; later corrections
  overwrite earlier values for the same period.
- **Sensors**: last file processed, files processed, last measure per meter, peak of the last complete
  day, and the latest value of each R64 series (indexes per time class, maximum power reached, overrun
  duration and energy, operating time).
- **History import**: a CSV `debut;kw_moyen` uploaded from the integration's options, or the action
  `enedis_entreprise.import_history`, for what came before the subscription.
- **Repairs**: files that cannot be decrypted (key changed), no file received for N days.
  Reconfiguration keeps the secrets left empty. Diagnostics with secrets removed and PRM numbered.
- **Icon and logo**, shipped in the integration's `brand/` folder (Home Assistant 2026.3 and later
  show them). Original artwork — a lightning bolt over a load curve — not the logo of Enedis.
- Minimum Home Assistant version 2025.1; the tests run on 2025.1 and on the current release.

Not verified yet on real data: a file deposited by Enedis on a server and collected over SFTP,
decryption of a file as Enedis sends it, daily kWh compared with the Enedis portal.
