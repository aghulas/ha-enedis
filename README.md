# Enedis entreprise (R6X) — Home Assistant integration

Unofficial integration, not affiliated with Enedis. *[Version française plus bas.](#français)*

Imports the data Enedis publishes for business customers through its *publications récurrentes*
(flux R6X) into Home Assistant's long-term statistics and Energy dashboard:

- **R63** — load curve (5-minute steps for meters above 36 kVA): hourly energy (kWh) and power
  (mean, min, max in kW) statistics, plus the peak of the last complete day;
- **R64** — indexes per time class, maximum power reached, overrun data: one sensor per series.

You download the archives from your Enedis business account and drop them in a folder Home Assistant
reads. There is **no login to the Enedis portal** from Home Assistant, no captcha and no Enedis
password stored anywhere: the integration only reads files you already have.

**Status: first public release (0.1.x), beta — see the [changelog](CHANGELOG.md).** What has and has
not been checked on real data is listed under [Limits](#limits-and-what-is-not-verified-yet). Please
read it before relying on the figures.

## How it works

```
Enedis business account ──download (you)──▶ folder on the Home Assistant host ──read every 30 min──▶ statistics
```

Enedis can also push the files by itself, on a *digital channel*, but its two channel types do not
fit a site that accepts no incoming connection (details in [`docs/api.md`](docs/api.md#delivery-who-connects-to-whom)):

- **E-mail**: not read by this integration.
- **FTP server**: Enedis connects to **your** server, in **plain FTP only** (passive mode, port 21,
  address `domain:21/folder`, login and password). That server must accept unencrypted FTP from the
  Internet. If you already have one elsewhere, the optional SFTP and FTPS sources below can collect
  from it; never run it on your Home Assistant host.

## Step by step

This integration is for holders of an Enedis **business account** (*compte client entreprise*,
mon-compte-entreprise.enedis.fr). It is not for residential Linky customers.

1. **Subscriptions.** In the business account, *Vos données énergétiques → Les services de données →
   Recevoir vos données régulièrement → Paramétrer vos abonnements*: subscribe to the load curve (R63)
   and / or the index (R64), **JSON** format (CSV is read too). Above 36 kVA the daily curve is the raw
   one; the corrected curve only comes weekly or monthly and overwrites the raw values when it
   arrives. Enedis takes a new subscription into account within 72 hours and only publishes from the
   subscription date onwards.
2. **Folder.** Create a folder Home Assistant can read, for example `/share/enedis` or
   `/media/enedis` on Home Assistant OS (see [The local folder](#the-local-folder)).
3. **Home Assistant.** Install the integration (below), add it, choose *A local folder*, enter the
   folder and leave the key empty.
4. **Files.** In the business account, *Vos abonnements* lists the published archives. Download them
   and copy them, unchanged, into the folder (with the Samba share add-on, for instance). Within 30
   minutes the *Last file processed* sensor gets a date and the statistics appear. Repeat as often as
   you like: archives already read are skipped.

## Installation

Requires Home Assistant 2025.1 or later: that is the oldest release the automated tests run on (they
also run on the current release; the pilot installation runs 2026.11). Icons are shown by Home
Assistant 2026.3 and later.

**Home Assistant 2026.11 or later — Marketplace:**

1. Settings → Marketplace → **Add from link** (upper right), enter `aghulas/ha-enedis`, then **Add**.
   Adding a repository by link asks you once to connect a GitHub account.
2. Open the repository page and select **Install**.

**Earlier versions — HACS:** HACS → Integrations → menu → *Custom repositories*, add
`https://github.com/aghulas/ha-enedis` as an *Integration*, install it, then restart Home Assistant.
[This link](https://my.home-assistant.io/redirect/hacs_repository/?owner=aghulas&repository=ha-enedis&category=integration)
opens that dialog pre-filled.

**Manually:** copy `custom_components/enedis_entreprise` into the `custom_components` folder of your
configuration, then restart Home Assistant.

## Configuration

*Settings → Devices & services → Add integration → Enedis entreprise (R6X)*, then choose where the
files are read:

| Source | What to enter | When |
|---|---|---|
| **Local folder** (recommended) | a folder Home Assistant can read; key left empty | Archives downloaded from the business account, or brought there by anything else. |
| SFTP | host, port (22), username, password, folder, key | Optional. A third-party server that receives Enedis' FTP deposit and also offers SFTP on the same folder. The host key is recorded at setup; a server showing another key later is refused. Password login only. |
| FTPS | host, port (21), username, password, folder, key | Optional. Same, for a server that offers FTPS. Explicit TLS only: Home Assistant never collects over plain FTP. |

The **key** (64 hexadecimal characters, shown with the channel in the business account) is only
needed for files Enedis sent on a channel: those are encrypted (AES-256). Archives downloaded from
the account are not, so leave it empty for them.

**Options** (*Configure*): restrict the import to some PRM (14 digits each), and the number of days
without any new file after which a repair issue is raised (3 by default — raise it if you only drop
files once a week).

### The local folder

- **Where.** On Home Assistant OS or Supervised, `/share/...`, `/media/...` and `/config/...` are all
  readable; `/share` and `/media` are reachable from the Samba share add-on. In a container
  installation, use a path mounted in the container. No `allowlist_external_dirs` entry is needed
  for this source.
- **What is read.** Every file of the folder and its subfolders whose name is an Enedis publication,
  as downloaded from the account — `ENEDIS_R63A_Q_CdC_<…>_<sequence>_<timestamp>.zip`,
  `ENEDIS_R64A_Q_INDEX_<…>_<sequence>_<timestamp>.zip` — or as the Enedis guide names them
  (`Enedis_<flux>_…_<timestamp>.zip`). Upper or lower case does not matter. The archive may also be a
  bare `.json` / `.csv` with such a name, or an encrypted file with the extra extension `.aes`.
  Flows R63A, R63B, R64A and R64B are recognised.
- **What is ignored.** Any other file, never opened — including a renamed archive (for instance
  `… (1).zip`, a duplicate made by the browser) and files above 50 MB.
- **When.** At startup, then every 30 minutes.
- **Duplicates.** Each publication is identified by its flow, request id and sequence number, read
  from the file names: the same archive dropped twice, or under another name in a subfolder, is read
  once. Writing the same data again would change nothing anyway; a later file covering the same
  period (corrected curve) overwrites the earlier values. Nothing is deleted or moved in the folder:
  clean it up yourself whenever you like.
- **Problems.** An archive that cannot be opened (damaged, or encrypted without the right key) raises
  a repair issue and is tried again at every poll. A recognised file whose content cannot be read is
  logged as a warning and skipped; unknown fields inside a file are skipped with a warning too.

### What you get

- Statistics `enedis_entreprise:<PRM>_energy` (kWh, hourly) and `enedis_entreprise:<PRM>_power` (kW,
  hourly mean / min / max); `…_energy_production` and `…_power_production` for injected energy.
  **Energy dashboard**: *Settings → Dashboards → Energy → Electricity grid → Add consumption*, and pick
  the `Enedis <PRM> consumption` statistic. Values are dated at their real time, so they appear when
  you drop the files — at best one day late, as Enedis publishes them.
- Sensors per meter: last measure received, peak of the last complete day (kW, with its time), and the
  latest value of each R64 series (active and reactive energy indexes per time class, maximum power
  reached, overrun duration / energy, operating time).
- Diagnostic sensors: last file processed, number of files processed.
- Repair issues: files that cannot be opened; no new file for N days.
- Diagnostics download with secrets removed and PRM numbers replaced by `PRM 1`, `PRM 2`…

### History before the subscription

*Configure → Import a history file* uploads a CSV with the columns `debut;kw_moyen` (start of the step
as ISO 8601 with its UTC offset; mean power in kW, decimal comma). Points already received from Enedis
are kept unless you choose to overwrite them. The action `enedis_entreprise.import_history` does the
same from a file in a folder Home Assistant allows (`allowlist_external_dirs`: `/config/www` and
`/media` by default). This is **not** the format of the CSV the Enedis portal exports by itself: you
have to convert it to these two columns.

## Limits and what is not verified yet

- **Not automatic.** Someone has to download the archives and drop them in the folder; the *no new
  file* repair issue is there to remind you.
- **Checked on real data:** two real archives downloaded from the business account (one R63A load
  curve, one R64A index, meter above 36 kVA) — their names are recognised and their content is read;
  outside Home Assistant, the day's curve gave 24 hourly values.
- **Not checked yet:** the same archives read by the integration inside Home Assistant (statistics and
  sensors as created), the daily kWh compared with the Enedis portal (the timestamp of a point is taken
  as the *start* of its step, in French legal time, which the real file supports), a corrected curve
  overwriting raw values, a daylight-saving day, several days in a row.
- Meters up to 36 kVA (R63B / R64B) are parsed from the guide's description only.
- Decryption follows Enedis' published note (AES-256-CBC, IV in the first 16 bytes) and is tested
  against files encrypted by the test suite only. SFTP and FTPS are tested against simulated servers
  only.
- Reactive power and voltage curves are not imported. There is no "overrun yesterday" sensor: whether
  the overrun counters are cumulative has to be read on real data first.
- Corrected data replaces raw data only for the last 60 days of points kept by the integration.
- Statistic identifiers and entity unique identifiers contain the PRM. Mind this when sharing
  screenshots.

## Privacy and security

Keys and passwords are stored in the configuration entry only, never logged, and removed from
diagnostics. PRM numbers are never logged. Nothing is sent anywhere: the integration only reads.
**Never expose an FTP or SFTP server to the Internet on your Home Assistant host.**

## Development

```
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy custom_components/enedis_entreprise && pytest
```

The format of the files is documented in [`docs/api.md`](docs/api.md). Test fixtures are synthetic;
never commit a real file, PRM, SIREN or key. Issues: <https://github.com/aghulas/ha-enedis/issues>
(remove PRM numbers from what you paste). License: MIT.

---

## Français

Intégration **non officielle**, sans lien avec Enedis. Elle importe dans les statistiques et le
tableau de bord Énergie de Home Assistant les données qu'Enedis publie pour les clients
**entreprise** : courbe de charge R63 (pas de 5 minutes au-dessus de 36 kVA) et index R64 (par classe
temporelle, puissance maximale atteinte, dépassements). Aucune connexion au portail Enedis depuis Home
Assistant, aucun captcha, aucun mot de passe Enedis.

- **Principe** : vous téléchargez les archives depuis le compte client entreprise (*Vos abonnements*)
  et les déposez telles quelles dans un dossier que Home Assistant relit toutes les 30 minutes
  (`/share/enedis` ou `/media/enedis` sur Home Assistant OS, par exemple via le module Samba). Ces
  archives ne sont pas chiffrées : laissez la clé vide.
- **Pourquoi pas le dépôt automatique** : Enedis n'envoie que par e-mail (non lu par l'intégration)
  ou en **FTP non chiffré** sur un serveur à vous, joignable depuis Internet (mode passif, port 21
  uniquement). Les sources SFTP et FTPS restent disponibles, en option, pour relever un tel serveur
  tiers ; n'en exposez jamais un sur la machine de Home Assistant.
- **Côté Enedis** : s'abonner aux publications récurrentes (courbe de charge et / ou index, format
  JSON). La prise en compte demande jusqu'à 72 heures ; rien n'est publié avant la date d'abonnement.
- **Installation** : Marketplace de Home Assistant 2026.11 (*Ajouter depuis un lien* →
  `aghulas/ha-enedis`) ou HACS en dépôt personnalisé ; Home Assistant 2025.1 au minimum.
- **Configuration** : *Paramètres → Appareils et services → Ajouter une intégration → Enedis
  entreprise (R6X)*, choisir *Un dossier local*, saisir le dossier.
- **Fichiers lus** : les archives au nom d'une publication Enedis (`ENEDIS_R63A_…zip`,
  `ENEDIS_R64A_…_INDEX_…zip`), sous-dossiers compris ; tout autre fichier est ignoré. Une même
  publication déposée deux fois n'est lue qu'une fois ; rien n'est supprimé du dossier.
- **Tableau de bord Énergie** : ajouter la statistique `Enedis <PRM> consumption` comme consommation
  du réseau électrique.
- **Limites (version bêta)** : le dépôt des fichiers reste manuel ; de vraies archives ont été lues,
  mais pas encore dans Home Assistant, et les kWh journaliers n'ont pas encore été comparés au portail.
