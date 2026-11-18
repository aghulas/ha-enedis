"""Synthetic R6X files, built from the format in docs/api.md. No real PRM, SIREN or key here."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta
from typing import Any

PRM = "00000000000042"
SIREN = "000000000"
KEY_HEX = "00112233445566778899aabbccddeeff" * 2
FMT = "%Y-%m-%d %H:%M:%S"
R63_NAME = "Enedis_R63A_Q_CdC_M0000TEST_00007_20260302063000.json"
R64_NAME = "Enedis_R64A_Q_Index_M0000TEST_00003_20260302063000.json"
R63_ARCHIVE = f"Enedis_R63A_Q_CdC_M0000TEST_{SIREN}_20260302063000.zip"


def header(code: str) -> dict[str, Any]:
    return {
        "header": {
            "siDemandeur": "LINCS",
            "typeDestinataire": "ENTREPRISE",
            "idDestinataire": "1",
            "codeFlux": code,
            "idDemande": "M0000TEST",
            "modePublication": "Q",
            "format": "JSON",
            "idPublication": "1",
            "publicationCrp": "non",
        },
        "echeances": {
            "type": "filEau",
            "horodateDebutPublication": "2026-03-02 02:00:00",
            "frequence": "2H",
        },
    }


def stamps(start: str, count: int, minutes: int = 5) -> list[str]:
    first = datetime.strptime(start, FMT)
    return [(first + timedelta(minutes=minutes * i)).strftime(FMT) for i in range(count)]


def r63_document(
    start: str = "2026-03-01 00:00:00", count: int = 288, etape: str = "BEST"
) -> dict[str, Any]:
    """One day at 5-minute steps: 12 kW by night, 40 kW from 08:00 to 18:00; one estimated point."""
    points = []
    for i, d in enumerate(stamps(start, count)):
        hour = datetime.strptime(d, FMT).hour
        point: dict[str, Any] = {
            "v": str(40000 if 8 <= hour < 18 else 12000),
            "d": d,
            "p": "PT5M",
            "n": "R",
            "iv": None,
            "ec": None,
        }
        if i == 3:
            point |= {"n": "E", "tc": "A"}
        points.append(point)
    return header("R63A") | {
        "mesures": [
            {
                "idPrm": PRM,
                "etapeMetier": etape,
                "periode": {"dateDebut": "2026-03-02 04:00:00", "dateFin": "2026-03-02 06:00:00"},
                "modeCalcul": "MESURE",
                "grandeur": [
                    {
                        "grandeurMetier": "CONS",
                        "grandeurPhysique": "PA",
                        "unite": "W",
                        "points": points,
                    }
                ],
            }
        ]
    }


def r64_document() -> dict[str, Any]:
    """Distributor grid with three time classes, plus PMA and overrun duration."""

    def classe(ident: str, label: str, value: int) -> dict[str, Any]:
        return {
            "idClasseTemporelle": ident,
            "libelleClasseTemporelle": label,
            "valeur": [{"d": "2026-03-02 04:29:58", "v": value, "iv": None}],
        }

    def grandeur(code: str, unit: str, classes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "grandeurMetier": "CONS",
            "grandeurPhysique": code,
            "unite": unit,
            "calendrier": [
                {
                    "idCalendrier": "D",
                    "libelleCalendrier": "Distributeur",
                    "libelleGrille": "Distributeur",
                    "classeTemporelle": classes,
                }
            ],
        }

    return header("R64A") | {
        "mesures": [
            {
                "idPrm": PRM,
                "periode": {"dateDebut": "2026-03-02 04:00:00", "dateFin": "2026-03-02 06:00:00"},
                "contexte": [
                    {
                        "etapeMetier": "BRUT",
                        "contexteReleve": "FMR",
                        "typeReleve": "RC",
                        "grandeur": [
                            grandeur(
                                "EA",
                                "Wh",
                                [
                                    classe("HPH", "Heures Pleines Hiver", 314603000),
                                    classe("HCH", "Heures Creuses Hiver", 118344000),
                                    classe("HPE", "Heures Pleines Eté", 494318000),
                                ],
                            ),
                            grandeur("PMA", "VA", [classe("HPH", "Heures Pleines Hiver", 61000)]),
                            grandeur("DD", "s", [classe("HPH", "Heures Pleines Hiver", 0)]),
                        ],
                    }
                ],
            }
        ]
    }


def as_json(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode()


R63_CSV_HEADER = (
    "Identifiant PRM;Date de début;Date de fin;Grandeur physique;Grandeur métier;Etape métier;"
    "Unité;Horodate;Valeur;Nature;Pas;Indice de vraisemblance;Etat complémentaire"
)
R64_CSV_HEADER = (
    "Identifiant PRM;Date de début;Date de fin;Grandeur physique;Grandeur métier;Unité;Horodate;"
    "Contexte de relève;Type de relève;Motif de relève;Grille;Identifiant calendrier;"
    "Libellé calendrier;Identifiant classe temporelle;Libellé classe temporelle;Cadran;Valeur;"
    "Indice de vraisemblance"
)


def r63_csv(start: str = "2026-03-01 00:00:00", count: int = 12) -> bytes:
    period = "2026-03-02 04:00:00;2026-03-02 06:00:00"
    rows = [
        f"{PRM};{period};PA;CONS;BRUT;W;{d};{100 + i};R;PT5M;null;null"
        for i, d in enumerate(stamps(start, count))
    ]
    return "\n".join([R63_CSV_HEADER, *rows, ""]).encode()


def r64_csv() -> bytes:
    start = f"{PRM};2026-03-02 04:00:00;2026-03-02 06:00:00"
    rows = [
        f"{start};EA;CONS;Wh;2026-03-02 00:00:00;FMR;RC;null;D;DI000003;null;HPH;"
        "Heures Pleines Hiver;EA1;9921;null",
        f"{start};EA;CONS;Wh;2026-03-02 00:00:00;FMR;RC;null;F;FC000018;null;BASE;Base;EA2;74421;0",
        f"{start};PMA;CONS;VA;2026-03-02 00:00:00;FMR;RC;null;D;DI000003;null;HPH;"
        "Heures Pleines Hiver;null;61000;null",
    ]
    return "\n".join([R64_CSV_HEADER, *rows, ""]).encode()


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()
