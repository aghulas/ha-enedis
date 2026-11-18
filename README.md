# Enedis entreprise (R6X) — Home Assistant integration

**Status: work in progress, never run against a real Enedis file yet.** Unofficial, not affiliated
with Enedis. Done: decryption and R63/R64 parsers; folder, IMAP (read-only), SFTP and FTPS sources;
hourly energy and power statistics; configuration form, sensors, diagnostics, Repairs; one-off history
import. Not done: "overrun yesterday" sensor, calibration on a real file.

Imports the data Enedis pushes to business customers through *publications récurrentes* (R63 load curve
at 5-minute steps for meters > 36 kVA, R64 indexes with max power reached and overruns) into Home
Assistant's statistics and Energy dashboard. Files are read from a mailbox (IMAP), a local folder or an
external SFTP/FTPS host — no login to the Enedis portal, no captcha, and no FTP server exposed on your
Home Assistant host. See `docs/`. License: MIT.

## Setup

1. In the Enedis business account, subscribe to the recurring publications R63 (load curve) and R64
   (index), JSON format, then create an e-mail or FTP contact channel and copy its key (64 hexadecimal
   characters).
2. In Home Assistant: *Settings → Devices & services → Add integration → Enedis entreprise*, choose
   where the files arrive (mailbox, local folder or external FTPS server) and paste the key.

History: Enedis only publishes from the subscription date onwards. The action
`enedis_entreprise.import_history` imports, once, a load curve exported from the Enedis portal (CSV
with the columns `debut;kw_moyen`); points already received from Enedis are kept unless `overwrite`.

SFTP: the server's host key is recorded at setup and a server showing another key later is refused.

The mailbox is opened read-only: nothing is deleted, moved or marked as read. **Do not expose an FTP
server to the Internet on your Home Assistant host** to receive the files: have Enedis deliver to a
mailbox or to an external FTP account, and let the integration pull from there.

---

*FR* — Intégration non officielle qui importe dans Home Assistant les données envoyées par Enedis aux
clients entreprise via les publications récurrentes (R63 courbe de charge, R64 index, puissance maximale
atteinte, dépassements), à partir d'une boîte mail, d'un dossier ou d'un SFTP externe.
