# Enedis entreprise (R6X) — Home Assistant integration

Unofficial integration, not affiliated with Enedis. *[Version française plus bas.](#français)*

Imports the data Enedis **pushes** to business customers through its *publications récurrentes*
(flux R6X) into Home Assistant's long-term statistics and Energy dashboard:

- **R63** — load curve (5-minute steps for meters above 36 kVA): hourly energy (kWh) and power
  (mean, min, max in kW) statistics, plus the peak of the last complete day;
- **R64** — indexes per time class, maximum power reached, overrun data: one sensor per series.

Enedis deposits the files on a server of yours; Home Assistant collects them there over **SFTP** (a
local folder and FTPS are supported too). There is **no login to the Enedis portal**, no captcha and
no Enedis password in Home Assistant: the integration only reads files Enedis already sent you.

**Status: first public release (0.1.x), beta — see the [changelog](CHANGELOG.md).** What has and has
not been checked on real data is listed under [Limits](#limits-and-what-is-not-verified-yet). Please
read it before relying on the figures.

## How the files travel

```
Enedis ──deposits──▶ file server outside your site ◀──collects (SFTP, outgoing)── Home Assistant
```

Enedis' documentation describes the channel as a file *"déposé sur un serveur FTP"*: **Enedis connects
to your server**, not the other way round. That server therefore has to be reachable from the
Internet — which the machine running Home Assistant should never be.

So the server sits **outside your site**: an account at a web host that gives FTP / SFTP access to a
folder, a managed SFTP service, or a small server you run elsewhere. Enedis writes into a folder
there; Home Assistant reads the same folder with an outgoing SFTP connection. Nothing is opened on
your network, and since the files are encrypted with the channel's key, the host only stores data
it cannot read.

Two things the public Enedis documents do not say, to check in the business account when you create
the channel: which protocols Enedis accepts for its deposit (they only say "FTP") and from which
addresses it connects. The protocol Enedis uses to deposit and the one Home Assistant uses to
collect need not be the same, as long as both reach the same folder.

## Step by step

This integration is for holders of an Enedis **business account** (*compte client entreprise*,
mon-compte-entreprise.enedis.fr). It is not for residential Linky customers.

1. **File server.** Get an account outside your site with a folder reserved for Enedis, reachable by
   Enedis for the deposit and by SFTP for Home Assistant. Use credentials that give access to that
   folder only.
2. **Subscriptions.** In the business account, *Vos données énergétiques → Les services de données →
   Recevoir vos données régulièrement → Paramétrer vos abonnements*: subscribe to the load curve (R63)
   and / or the index (R64), **JSON** format (CSV is read too). Above 36 kVA the daily curve is the raw
   one; the corrected curve only comes weekly or monthly and overwrites the raw values when it arrives.
3. **Channel.** *Gestion de votre entreprise → Vos canaux numériques*: create an **FTP** channel with
   the address, credentials and folder of your server, then link the subscriptions to it (Enedis
   activates a new subscription within 72 hours). Copy the channel's **key** (64 hexadecimal
   characters): files sent on a channel are encrypted with it. Modifying the channel changes the key.
4. **Home Assistant.** Install the integration (below), add it, choose *An external SFTP server* and
   enter the server, the folder and the key.
5. **First file.** Enedis only publishes from the subscription date onwards, one day late. When the
   first file is in, the *Last file processed* sensor gets a date and the statistics appear.

**Do not expose an FTP or SFTP server to the Internet on your Home Assistant host** to receive the
files.

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
| **SFTP** (recommended) | host, port (22), username, password, folder, key | The server's host key is recorded at setup; a server showing another key later is refused. Password login only. |
| Local folder | a path Home Assistant can read (`/share/...`, `/media/...`), optional key | For files brought there by something else, or plain zips downloaded from the business account (no key needed). |
| FTPS | host, port (21), username, password, folder, key | For hosts that offer no SFTP. Explicit TLS only; plain FTP is refused. |

Files are only downloaded: nothing is deleted, moved or renamed on the server, so the folder grows by
a few files a day — clean it up from time to time on the server side.

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

- **No file deposited by Enedis on a server has been read yet.** The SFTP source is tested against a
  simulated server, never against a real host, and the deposit itself (protocol accepted by Enedis,
  file names and extension as deposited) has not been observed.
- **Encrypted files as Enedis sends them have not been read yet.** Decryption follows Enedis' published
  note (AES-256-CBC, IV in the first 16 bytes) and is tested against files encrypted by the test
  suite. The real files read so far were plain zips downloaded from the business account, through
  the folder source.
- SFTP logs in with a password; key-based login is not supported. FTPS is tested against a simulated
  server only.
- There is no e-mail source: Enedis can also send the files by e-mail, but this integration does not
  read a mailbox.
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
R64 (par classe temporelle, puissance maximale atteinte, dépassements). Aucune connexion au portail
Enedis, aucun captcha, aucun mot de passe Enedis dans Home Assistant.

- **Circulation des fichiers** : c'est Enedis qui dépose les fichiers sur un serveur à vous. Ce
  serveur doit donc être joignable depuis Internet : placez-le **hors de votre site** (hébergement
  web avec accès FTP / SFTP, service SFTP géré…). Home Assistant vient y relever les fichiers par une
  connexion SFTP **sortante** ; aucun port n'est ouvert chez vous. N'exposez jamais un serveur FTP ou
  SFTP sur Internet depuis la machine qui héberge Home Assistant.
- **Côté Enedis** : dans le compte client entreprise, s'abonner aux publications récurrentes (courbe
  de charge et / ou index, format JSON), créer un canal numérique **FTP** vers ce serveur, y associer
  les abonnements, puis copier la clé du canal (64 caractères hexadécimaux).
- **Installation** : Marketplace de Home Assistant 2026.11 (*Ajouter depuis un lien* →
  `aghulas/ha-enedis`) ou HACS en dépôt personnalisé ; Home Assistant 2025.1 au minimum.
- **Configuration** : *Paramètres → Appareils et services → Ajouter une intégration → Enedis
  entreprise (R6X)*, choisir *Un serveur SFTP externe*, saisir le serveur, le dossier et la clé.
  Un dossier local et le FTPS restent possibles.
- **Tableau de bord Énergie** : ajouter la statistique `Enedis <PRM> consumption` comme consommation
  du réseau électrique. Les données arrivent avec un jour de décalage.
- **Limites (version bêta)** : aucun fichier déposé par Enedis sur un serveur n'a encore été lu, le
  déchiffrement n'est pas vérifié sur un fichier réellement envoyé par Enedis, et les kWh journaliers
  n'ont pas encore été comparés au portail.
