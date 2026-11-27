# Enedis entreprise (R6X) — Home Assistant integration

Unofficial integration, not affiliated with Enedis. *[Version française plus bas.](#français)*

Imports the data Enedis **pushes** to business customers through its *publications récurrentes*
(flux R6X) into Home Assistant's long-term statistics and Energy dashboard:

- **R63** — load curve (5-minute steps for meters above 36 kVA): hourly energy (kWh) and power
  (mean, min, max in kW) statistics, plus the peak of the last complete day;
- **R64** — indexes per time class, maximum power reached, overrun data: one sensor per series.

The files are read from a mailbox (IMAP), a local folder or an external SFTP / FTPS host. There is
**no login to the Enedis portal**, no captcha and no Enedis password in Home Assistant: the
integration only reads files Enedis already sent you.

**Status: first public release (0.1.x), beta — see the [changelog](CHANGELOG.md).** What has and has
not been checked on real data is listed under [Limits](#limits-and-what-is-not-verified-yet). Please
read it before relying on the figures.

## What you need on the Enedis side

This integration is for holders of an Enedis **business account** (*compte client entreprise*,
mon-compte-entreprise.enedis.fr). It is not for residential Linky customers.

1. In the business account, *Vos données énergétiques → Les services de données → Recevoir vos données
   régulièrement → Paramétrer vos abonnements*: subscribe to the load curve (R63) and / or the index
   (R64), **JSON** format (CSV is read too). Above 36 kVA the daily curve is the raw one; the corrected
   curve only comes weekly or monthly and overwrites the raw values when it arrives.
2. *Gestion de votre entreprise → Vos canaux numériques*: create an **e-mail** or **FTP** channel and
   link the subscriptions to it (Enedis activates a new subscription within 72 hours). Copy the
   channel's **key** (64 hexadecimal characters): files sent on a channel are encrypted with it.
3. Enedis only publishes from the subscription date onwards.

Use a dedicated mailbox, or an FTP / SFTP account at an external host. **Do not expose an FTP server
to the Internet on your Home Assistant host** to receive the files: let Enedis deliver elsewhere and
let the integration pull from there.

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
files arrive:

| Source | What to enter | Notes |
|---|---|---|
| Mailbox (IMAP) | server, port (993), username, password, folder, optional sender filter, key | Opened **read-only**: nothing is deleted, moved or marked as read. TLS only. |
| Local folder | a path Home Assistant can read (`/share/...`, `/media/...`), optional key | For files dropped by anything else. Plain zips downloaded from the business account need no key. |
| SFTP | host, port (22), username, password, folder, key | The server's host key is recorded at setup; a server showing another key later is refused. |
| FTPS | host, port (21), username, password, folder, key | Explicit TLS only; plain FTP is refused. |

The source is polled every 30 minutes. Each file is processed once; reading a file again changes
nothing, and a later correction of the same period overwrites the earlier values.

**Options** (*Configure*): restrict the import to some PRM (14 digits each), and the number of days
without any file after which a repair issue is raised (3 by default).

**New key**: when Enedis issues a new key for the channel, files can no longer be decrypted and a
repair issue appears. Use *Reconfigure* and paste the new key; fields left empty keep their value and
the files left aside are read again.

### What you get

- Statistics `enedis_entreprise:<PRM>_energy` (kWh, hourly) and `enedis_entreprise:<PRM>_power` (kW,
  hourly mean / min / max); `…_energy_production` and `…_power_production` for injected energy.
  **Energy dashboard**: *Settings → Dashboards → Energy → Electricity grid → Add consumption*, and pick
  the `Enedis <PRM> consumption` statistic. Values are dated at their real time, so data arrives one
  day late in the dashboard — that is how Enedis publishes it.
- Sensors per meter: last measure received, peak of the last complete day (kW, with its time), and the
  latest value of each R64 series (active and reactive energy indexes per time class, maximum power
  reached, overrun duration / energy, operating time).
- Diagnostic sensors: last file processed, number of files processed.
- Repair issues: files that cannot be decrypted; no file received for N days.
- Diagnostics download with secrets removed and PRM numbers replaced by `PRM 1`, `PRM 2`…

### History before the subscription

*Configure → Import a history file* uploads a CSV with the columns `debut;kw_moyen` (start of the step
as ISO 8601 with its UTC offset; mean power in kW, decimal comma). Points already received from Enedis
are kept unless you choose to overwrite them. The action `enedis_entreprise.import_history` does the
same from a file already on the Home Assistant host. This is **not** the format of the CSV the Enedis
portal exports by itself: you have to convert it to these two columns.

## Limits and what is not verified yet

- **Encrypted files as Enedis sends them have not been read yet.** Decryption follows Enedis' published
  note (AES-256-CBC, IV in the first 16 bytes) and is tested against files encrypted by the test
  suite, not against a real attachment. The real files read so far were plain zips downloaded from
  the business account, through the folder source.
- **The mailbox source has not met a real Enedis e-mail yet** (attachment name, sender). It is tested
  against a local fake IMAP server. SFTP and FTPS are tested the same way, never against a real host.
- **Daily kWh have not been compared with the Enedis portal yet.** The timestamp of a point is taken as
  the *start* of its step, in French legal time, which the first real files support.
- Meters above 36 kVA (R63A / R64A) are what real files were read for. The formats for meters up to
  36 kVA (R63B / R64B) are parsed from the guide's description only.
- Reactive power and voltage curves are not imported. There is no "overrun yesterday" sensor: whether
  the overrun counters are cumulative has to be read on real data first.
- Corrected data replaces raw data only for the last 60 days of points kept by the integration.
- Statistic identifiers and entity unique identifiers contain the PRM. Mind this when sharing
  screenshots.

## Privacy and security

The key and passwords are stored in the configuration entry only, never logged, and removed from
diagnostics. PRM numbers are never logged. Nothing is sent anywhere: the integration only reads.

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
tableau de bord Énergie de Home Assistant les données qu'Enedis envoie aux clients **entreprise** par
les publications récurrentes : courbe de charge R63 (pas de 5 minutes au-dessus de 36 kVA) et index
R64 (par classe temporelle, puissance maximale atteinte, dépassements). Les fichiers sont lus dans une
boîte mail (IMAP, en lecture seule), un dossier local ou un serveur SFTP / FTPS externe : aucune
connexion au portail Enedis, aucun captcha, aucun mot de passe Enedis dans Home Assistant.

- **Côté Enedis** : dans le compte client entreprise, s'abonner aux publications récurrentes (courbe
  de charge et / ou index, format JSON), créer un canal numérique e-mail ou FTP, y associer les
  abonnements, puis copier la clé du canal (64 caractères hexadécimaux).
- **Installation** : Marketplace de Home Assistant 2026.11 (*Ajouter depuis un lien* →
  `aghulas/ha-enedis`) ou HACS en dépôt personnalisé ; Home Assistant 2025.1 au minimum.
- **Configuration** : *Paramètres → Appareils et services → Ajouter une intégration → Enedis
  entreprise (R6X)*, choisir la source des fichiers et coller la clé.
- **Tableau de bord Énergie** : ajouter la statistique `Enedis <PRM> consumption` comme consommation
  du réseau électrique. Les données arrivent avec un jour de décalage.
- **Limites (version bêta)** : le déchiffrement des fichiers réellement envoyés par Enedis et la
  lecture d'un vrai e-mail Enedis ne sont pas encore vérifiés ; les kWh journaliers n'ont pas encore
  été comparés au portail. N'exposez jamais un serveur FTP sur Internet depuis la machine qui héberge
  Home Assistant.
