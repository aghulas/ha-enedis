# Enedis recurring publications (flux R6X) — what we know

Sources: Enedis guide *« Guide d'implémentation des flux R6X via compte client entreprise, de
publication récurrente de données de mesures : R63 (courbe de charge), R64 (index) »*, v2.0 (29/11/2023),
enedis.fr/media/3751/download; note **Enedis-NOI-CF_107E** (decryption of documents sent on a business
customer's digital channels), enedis.fr/media/2009/download. **To complete in session 1** (exact crypto).

## Setup (user side, business account administrator)

- Subscriptions ("abonnements") to recurring publications: R63 (load curve) and/or R64 (index);
  frequency Q (daily) / H (weekly) / M (monthly); format JSON or CSV (CSV only below 100 PRM); for > 36 kVA
  curves, `BRUT` or `BEST` (estimated/corrected included).
- Taken into account within **72 h**, then associable to a **digital channel**: e-mail or FTP. Outside
  the business account, files are **encrypted (AES-256, dynamic IV)**; the key is created with the
  channel in the business account.

## Archive and file names

`Enedis_<codeFlux>_<modePublication>_<typeDonnees>_<idDemande>_<SIREN>_<horodate>.zip` containing
`Enedis_<codeFlux>_<modePublication>_<typeDonnees>_<idDemande>_<numSequence>_<horodate>.<json|csv>`

- `codeFlux`: `R63A` curve > 36 kVA, `R63B` curve ≤ 36 kVA (Linky), `R64A` index > 36 kVA, `R64B` index Linky
- `modePublication`: `Q`, `H`, `M`; `typeDonnees`: `CdC` or `Index`; `numSequence`: 00001–99999;
  `horodate`: `AAAAMMJJHHMMSS`. One archive per SIREN and data type.
- Publication `type`: `immediat`, `heureFixe`, `filEau` (frequency `2H`, `4H`, `6H`, `12H`, `24H`);
  `dateDebut`/`dateFin` = acquisition window in Enedis' IS (several files per day possible).

## JSON header

`siDemandeur` (LINCS), `typeDestinataire` (ENTREPRISE), `idDestinataire`, `codeFlux`, `idDemande`,
`modePublication`, `format` (JSON), `idPublication`, `publicationCrp`.

## R63 — load curve

CSV columns (`;`): PRM, Date de début, Date de fin, Grandeur physique, Grandeur métier, Etape métier,
Unité, Horodate, Valeur, Nature, Pas, Indice de vraisemblance, Etat complémentaire.
JSON point fields: `v` value (integer), `d` timestamp, `p` step, `n` nature, `tc` completion type
(BEST only), `iv`, `ec` (Linky only).

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

- > 36 kVA: no totaliser; indexes per distributor (`D`) or supplier (`F`) grid, `codeCadran` like
  `EA1`, `EA2`…; contexts `FMR` (regular, with `RM` monthly / `RC` current), `CRD`, `CRI`.
- `grandeurPhysique` (> 36 kVA): `EA` Wh, `ER` / `ERC` / `ERI` VArh, **`PMA` max power reached (VA)**,
  **`DD` overrun duration (s)**, **`DE` overrun energy (Wh)**, **`DQ` quadratic overrun (Wh)**,
  `TF` operating time (s).

## Decryption — TODO session 1

From NOI-CF_107E: AES-256 with dynamic IV, key per digital channel (created with the channel in the
business account). To document precisely: key encoding, IV location (prefix?), padding, whether the zip
or each file is encrypted, file extension of encrypted payloads, how the key is delivered/rotated.
