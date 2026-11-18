# Enedis entreprise (R6X) — Home Assistant integration

**Status: scaffolding — not usable yet.** Unofficial, not affiliated with Enedis.

Imports the data Enedis pushes to business customers through *publications récurrentes* (R63 load curve
at 5-minute steps for meters > 36 kVA, R64 indexes with max power reached and overruns) into Home
Assistant's statistics and Energy dashboard. Files are read from a mailbox (IMAP), a local folder or an
external SFTP/FTPS host — no login to the Enedis portal, no captcha, and no FTP server exposed on your
Home Assistant host. See `docs/`. License: MIT.

---

*FR* — Intégration non officielle qui importe dans Home Assistant les données envoyées par Enedis aux
clients entreprise via les publications récurrentes (R63 courbe de charge, R64 index, puissance maximale
atteinte, dépassements), à partir d'une boîte mail, d'un dossier ou d'un SFTP externe.
