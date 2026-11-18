# Enedis recurring publications (flux R6X) — what we know

Sources: Enedis guide *« Guide d'implémentation des flux R6X via compte client entreprise, de
publication récurrente de données de mesures : R63 (courbe de charge), R64 (index) »*, v2.0 (29/11/2023),
enedis.fr/media/3751/download; note **Enedis-MOP-CF_080E** v1 (15/09/2025; replaces, unchanged,
**Enedis-NOI-CF_107E** v3 of 11/09/2024 — decryption of documents sent on a business customer's digital
channels), enedis.fr/media/2009/download. Both read on 2026-11-18. Points the documents do **not**
settle are listed under "Open questions" — to calibrate on the first real file.

## Setup (user side, business account administrator)

- Subscriptions ("abonnements") to recurring publications: R63 (load curve) and/or R64 (index);
  frequency Q (daily) / H (weekly) / M (monthly); format JSON or CSV (CSV only below 100 PRM); for > 36 kVA
  curves, `BRUT` or `BEST` (estimated/corrected included).
- Taken into account within **72 h**, then associable to a **digital channel**: e-mail or FTP. Outside
  the business account, files are **encrypted (AES-256, dynamic IV)**; the key is created with the
  channel in the business account.

### As seen in the business account (2026-11-18)

- *Vos données énergétiques → Les services de données → Recevoir vos données régulièrement →
  Paramétrer vos abonnements → Comptage supérieur à 36 kVA ou HTA*: one row per data type and
  frequency, CSV or JSON, a "S'abonner" switch, then *Enregistrer les modifications*.
- Rows offered above 36 kVA: **Index** (daily / weekly / monthly), **Courbe de charge brute** (daily /
  weekly / monthly), **Courbe de charge corrigée** (**weekly / monthly only — no daily**). So daily data
  is raw (`BRUT`); corrected data (`BEST`) comes at best once a week and overwrites it.
- *Vos abonnements* also lists the published files for download from the account itself.
- *Gestion de votre entreprise → Vos canaux numériques*: e-mail / FTP channels; each shows its key
  (masked, with a "Copier" button) and a "Générer une nouvelle clé" button.
- Sending a subscription to a channel is the "par e-mail/serveur FTP" link of its row, greyed out
  right after subscribing (expected to open after the activation delay).

## Archive and file names

`Enedis_<codeFlux>_<modePublication>_<typeDonnees>_<idDemande>_<SIREN>_<horodate>.zip` containing
`Enedis_<codeFlux>_<modePublication>_<typeDonnees>_<idDemande>_<numSequence>_<horodate>.<json|csv>`

- `codeFlux`: `R63A` curve > 36 kVA, `R63B` curve ≤ 36 kVA (Linky), `R64A` index > 36 kVA, `R64B` index Linky
- `modePublication`: `Q`, `H`, `M`; `typeDonnees`: `CdC` or `Index`; `numSequence`: 00001–99999;
  `horodate`: `AAAAMMJJHHMMSS`. One archive per SIREN and data type.
- Publication `type`: `immediat`, `heureFixe`, `filEau` (frequency `2H`, `4H`, `6H`, `12H`, `24H`);
  `dateDebut`/`dateFin` = acquisition window in Enedis' IS (several files per day possible).

## JSON structure (common)

Top level: `header` (1), `echeances` (0-1), `mesures` (array, 1-n).

- `header`: `siDemandeur` (LINCS), `typeDestinataire` (ENTREPRISE), `idDestinataire`, `codeFlux`,
  `idDemande`, `modePublication`, `idCanalContact` (in the class diagram, absent from the examples),
  `format` (JSON), `idPublication`, `publicationCrp` (`oui` / `non`). Key order is not stable.
- `echeances`: `type` (`immediat`, `heureFixe`, `filEau`), `horodateDebutPublication` (absent for
  `immediat`), `frequence` (`2H`…`24H`, `filEau` only).
- All timestamps are `AAAA-MM-JJ hh:mm:ss`, **without time zone**. Missing values are JSON `null`; in
  CSV they are the literal text `null`.

## R63 — load curve

CSV columns (`;`): PRM, Date de début, Date de fin, Grandeur physique, Grandeur métier, Etape métier,
Unité, Horodate, Valeur, Nature, Pas, Indice de vraisemblance, Etat complémentaire.
CSV example row: `<prm>;2023-09-19 06:00:00;2023-09-19 08:00:00;PA;CONS;BRUT;W;2023-09-18 00:00:00;100;R;PT5M;null;null`
(first column header is `Identifiant PRM`; no `tc` column in CSV).

JSON: `mesures[]` = `idPrm`, `etapeMetier`, `periode.dateDebut` / `periode.dateFin`, `modeCalcul`
(MESURE), `grandeur[]` (1-6) = `grandeurMetier`, `grandeurPhysique`, `unite`, `points[]`.
Point fields: `v` value (integer, **sent as a string** in the guide's example: `"v":"4000"`), `d`
timestamp, `p` step, `n` nature, `tc` completion type (BEST only, natures C / E), `iv`, `ec` (Linky only).

- `grandeurMetier`: `CONS` / `PROD`; `grandeurPhysique`: `PA` (W), `PRI` / `PRC` (VAr, > 36 kVA), `E`
  (V, > 36 kVA); `etapeMetier`: `BRUT` / `BEST`.
- `p`: `PT5M` for > 36 kVA (C1-C4); `PT10M/15M/30M/60M` for Linky.
- **Value = mean power over the step** → energy (Wh) = W × step(h).
- Natures `n`: B raw (Linky), R real (> 36 kVA), C corrected, D imported, E estimated, H rebuilt (clock
  change), P rebuilt + outage, S outage, T short outage, F outage start, G outage end.
- Completion types `tc` (BEST): F, G, N, H, I, O, J, K, L, C, A, M (see guide §3.3.1.2).

## R64 — indexes

CSV columns: PRM, Date de début, Date de fin, Grandeur physique, Grandeur métier, Unité, Horodate,
Contexte de relève, Type de relève, Motif de relève, Grille, Identifiant calendrier, Libellé calendrier,
Identifiant classe temporelle, Libellé classe temporelle, Cadran, Valeur, Indice de vraisemblance.
Example row (Linky): `<prm>;<début>;<fin>;EA;CONS;Wh;2023-09-19 00:00:00;COL;AQ;null;D;DI000003;null;HPB;Heures Pleines Saison Basse;IDX_EAS_D4;1221;0`
(no `Etape métier` column; grid is `D` / `F` in CSV, `Distributeur` / `Fournisseur` in JSON).

JSON: `mesures[]` = `idPrm`, `periode`, `contexte[]` (1-16) = `etapeMetier` (BRUT), `contexteReleve`,
`typeReleve`, `motifReleve`, `grandeur[]` (1-18) = `grandeurMetier`, `grandeurPhysique`, `unite`, then
either `cadranTotalisateur` (0-1, Linky totaliser: `codeCadran`, `valeur[]`) or `calendrier[]` =
`idCalendrier`, `libelleCalendrier`, `libelleGrille`, `classeTemporelle[]` (0-16) =
`idClasseTemporelle`, `libelleClasseTemporelle`, `codeCadran`, `valeur[]` = `d`, `v` (JSON number), `iv`.
In the guide's > 36 kVA example `codeCadran` is absent and the classes are `HPE`, `HPH`, `HCH`… → the
stable key of an index series is (grid, calendar, time class), not the dial.

- > 36 kVA: no totaliser; indexes per distributor (`D`) or supplier (`F`) grid, `codeCadran` like
  `EA1`, `EA2`…; contexts `FMR` (regular, with `RM` monthly / `RC` current), `CRD`, `CRI`, `RHF`
  (fixed-hour reading near midnight, meant to replace the others eventually); Linky: `COL`, `TOP`, `CRI`.
  Reading types: `AQ`, `AV`, `AS`, `AP` (Linky), `LC`, `RM`, `RC`.
- `grandeurPhysique` (> 36 kVA): `EA` Wh, `ER` / `ERC` / `ERI` VArh, **`PMA` max power reached (VA)**,
  **`DD` overrun duration (s)**, **`DE` overrun energy (Wh)**, **`DQ` quadratic overrun (Wh)**,
  `TF` operating time (s).

## Decryption (method "AES256 IV dyn")

- **AES-256, CBC mode, `PKCS5Padding`** (= PKCS#7 for a 16-byte block). Footnote of the note: "in case
  of anomaly, the padding can be removed" → we fall back to no-padding when unpadding fails but the
  plaintext still looks like a zip / JSON / CSV.
- **IV**: 128 random bits per file, stored in the **first 16 bytes** of the encrypted file; the AES
  blocks follow. Raw binary, no base64.
- **Key**: one symmetric key **per contact channel** (not per flux), shown in the business account
  ("Mes canaux de contact", key icon) as **64 hexadecimal characters**. Created with the channel,
  **replaced whenever the channel is modified** (later files use the new key). No validity period stated.
- Enedis' own tool writes the decrypted file next to the original with the prefix `lisible`.
- Flux covered since Feb. 2023: R63 (listed as "R6343") and R64 ("R6419").

Implementation: `api/decrypt.py` (`cryptography`, already shipped with Home Assistant).
`open_publication()` accepts the encrypted file, an already decrypted zip, or a bare JSON / CSV.

## Open questions (calibrate on the first real file)

1. **What is encrypted**: the note says "the file" — assumed to be the whole `.zip` attachment
   (decrypt → zip → JSON/CSV). Extension of the attachment as received unknown (`.zip`?).
2. **Time zone of `d`**: not stated. Assumed French legal time (Europe/Paris), like the portal.
3. **Does `d` mark the start or the end of the step?** Not stated. The example starts at `00:00:00`;
   assumed **start** of step. Parsers keep naive timestamps; the convention is applied in one place
   (`localize()`), to flip after comparing a day's kWh with the portal (`enedis_energie`).
4. Daylight-saving days: nothing in the guide beyond natures `H` / `P`. `localize()` resolves the
   repeated 02:00–03:00 hour by order of appearance (same approach as `enedis-mcp`).
5. `v` type in real R63 files (string vs number), CSV encoding (UTF-8 assumed, BOM tolerated,
   Latin-1 fallback), exact attachment / e-mail sender and subject (needed for the IMAP source).
6. How BEST corrections are re-published (same timestamps in a later file is assumed → overwrite).
