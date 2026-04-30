"""
ingest.py — Extraction du PDF des résultats électoraux CI 2025
================================================================

STRUCTURE DU TABLEAU (16 colonnes fixes) :
  col[0]  : Région (texte vertical, lettres séparées par \n, à l'envers)
  col[1]  : Numéro de circonscription (entier) ou None/'' entre deux circs
  col[2]  : Nom de la circonscription
  col[3]  : NB_BV (bureaux de vote)
  col[4]  : Inscrits
  col[5]  : Votants
  col[6]  : Taux de participation
  col[7]  : Bulletins nuls
  col[8]  : Suffrages exprimés
  col[9]  : Bulletins blancs (nombre)
  col[10] : Bulletins blancs (%)
  col[11] : Parti / Groupement politique
  col[12] : Nom du candidat / liste
  col[13] : Score (voix)
  col[14] : Pourcentage candidat
  col[15] : "ELU(E)" si élu, vide sinon

CAS PARTICULIERS (chevauchements de page) :
  CAS A — col[1]='' + stats dans col[4-10] + ELU(E) :
    Le PDF fusionne les stats d'une nouvelle circ et son élu sur une même ligne.
    → déclencher changement de circ + enregistrer l'élu (circs 6, 42, 65, 135)

  CAS B — col[1]='' + PAS de stats + ELU(E) :
    Dernier élu de la circ courante sans numéro (cellule fusionnée visuellement).
    → candidat normal de la circ courante (circs 46, 114)
"""

import pdfplumber
import pandas as pd
import os
import re

REGION_MAP = {
    "AGNEBY-TIASSA":     "AGNEBY-TIASSA",
    "GBEKE":             "GBÊKÊ",
    "GBOKLE":            "GBÔKLÊ",
    "BERE":              "BERE",
    "BAGOUE":            "BAGOUE",
    "NAWA":              "NAWA",
    "FOLON":             "FOLON",
    "GOH":               "GOH",
    "PORO":              "PORO",
    "BAFING":            "BAFING",
    "BOUNKANI":          "BOUNKANI",
    "CAVALLY":           "CAVALLY",
    "GONTOUGO":          "GONTOUGO",
    "GRANDSPONTS":       "GRANDS-PONTS",
    "GUEMON":            "GUEMON",
    "HAMBOL":            "HAMBOL",
    "HAUT-SASSANDRA":    "HAUT-SASSANDRA",
    "IFFOU":             "IFFOU",
    "INDENIE-DJUABLIN":  "INDENIE-DJUABLIN",
    "KABADOUGOU":        "KABADOUGOU",
    "LAME":              "LA ME",
    "LOH-DJIBOUA":       "LOH-DJIBOUA",
    "LOH-DJIBOU":        "LOH-DJIBOUA",
    "MARAHOUE":          "MARAHOUE",
    "MORONOU":           "MORONOU",
    "'N'ZI":             "N'ZI",
    "N'ZI":              "N'ZI",
    "SUD-COMOE":         "SUD-COMOE",
    "TCHOLOGO":          "TCHOLOGO",
    "TONKPI":            "TONKPI",
    "WORODOUGOU":        "WORODOUGOU",
    "BELIER":            "BELIER",
    "SAN-PEDRO":         "SAN-PEDRO",
    "UTONOMED'ABIDJAN":  "DISTRICT AUTONOME D'ABIDJAN",
    "'UTONOMED'ABIDJAN": "DISTRICT AUTONOME D'ABIDJAN",
    "EDEYAMOUSSOUKRO":   "DISTRICT AUTONOME DE YAMOUSSOUKRO",
    "'EDEYAMOUSSOUKRO":  "DISTRICT AUTONOME DE YAMOUSSOUKRO",
}


def decoder_region(texte_brut):
    if not texte_brut:
        return None
    texte_brut = texte_brut.strip()
    if texte_brut in {"REGI", "ON", "TOTAL", ""}:
        return None
    nom = "".join(texte_brut.split("\n"))[::-1].strip().upper()
    if nom in REGION_MAP:
        return REGION_MAP[nom]
    for cle, valeur in REGION_MAP.items():
        if cle.upper() in nom or nom in cle.upper():
            return valeur
    return None


def clean_number(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    if s in ("", "-", "None", "nan"):
        return 0.0
    s = re.sub(r"[\s\u00a0]", "", s).replace("%", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def est_entete(row):
    return (
        row[0] in ("REGI", "ON")
        or row[1] == "CIRCONSCRIPTION"
        or row[11] in ("GROUPEMENTS / PARTIS", "POLITIQUES")
    )


def extraire_stats(row):
    return {
        "nb_bv":              int(clean_number(row[3])),
        "inscrits":           int(clean_number(row[4])),
        "votants":            int(clean_number(row[5])),
        "taux_participation": clean_number(row[6]),
        "bulletins_nuls":     int(clean_number(row[7])),
        "suf_exprimes":       int(clean_number(row[8])),
        "blancs_nombre":      int(clean_number(row[9])),
        "blancs_pct":         clean_number(row[10]),
    }


CANDIDATS_IGNORER = {
    "CANDIDATS / LISTES DE CANDIDATS", "TOTAL",
    "TOTAL GENERAL", "", "NONE",
}


def make_record(region, circ_num, circ_nom, stats, row, est_elu, num_page):
    nom_candidat = str(row[12]).replace("\n", " ").strip() if row[12] else ""
    parti = str(row[11]).strip() if row[11] else "INDEPENDANT"
    return {
        "region":             region,
        "code_circ":          circ_num,
        "nom_circ":           circ_nom,
        "nb_bv":              stats["nb_bv"],
        "inscrits":           stats["inscrits"],
        "votants":            stats["votants"],
        "taux_participation": stats["taux_participation"],
        "bulletins_nuls":     stats["bulletins_nuls"],
        "suf_exprimes":       stats["suf_exprimes"],
        "blancs_nombre":      stats["blancs_nombre"],
        "blancs_pct":         stats["blancs_pct"],
        "parti":              parti,
        "nom_candidat":       nom_candidat,
        "voix_obtenues":      int(clean_number(row[13])),
        "pourcentage":        clean_number(row[14]),
        "est_elu":            "OUI" if est_elu else "NON",
        "page_source":        num_page,
    }


def extraire_donnees_pdf(pdf_path):
    records = []
    region_courante = "INCONNUE"
    circ_num = 0
    circ_nom = ""
    stats = {"nb_bv": 0, "inscrits": 0, "votants": 0,
             "taux_participation": 0.0, "bulletins_nuls": 0,
             "suf_exprimes": 0, "blancs_nombre": 0, "blancs_pct": 0.0}

    with pdfplumber.open(pdf_path) as pdf:
        for num_page, page in enumerate(pdf.pages, start=1):
            tableau = page.extract_table()
            if not tableau:
                continue

            for row in tableau:
                while len(row) < 16:
                    row.append(None)

                if est_entete(row):
                    continue

                # 1. Région
                region_decodee = decoder_region(row[0])
                if region_decodee:
                    region_courante = region_decodee

                col1 = row[1]
                col1_str = str(col1).strip() if col1 is not None else ""
                est_vide_explicite = (col1 is not None and col1_str == "")
                a_stats = (row[4] is not None and str(row[4]).strip() not in ("", "None"))
                a_elu   = (row[15] is not None and "ELU" in str(row[15]).upper())

                nom_candidat = str(row[12]).replace("\n", " ").strip() if row[12] else ""
                candidat_valide = (
                    nom_candidat.upper() not in CANDIDATS_IGNORER
                    and len(nom_candidat) >= 3
                )

                # 2. CAS A : chevauchement avec stats → nouvelle circ + élu
                if est_vide_explicite and a_stats and a_elu:
                    stats_caseA = extraire_stats(row)
                    prochain_num = circ_num + 1
                    if candidat_valide:
                        rec = make_record(region_courante, prochain_num, "",
                                          stats_caseA, row, True, num_page)
                        records.append(rec)
                    # Mettre les stats en mémoire pour la prochaine circ
                    stats = stats_caseA
                    continue

                # 3. Changement de circ normal (col[1] est un entier)
                if col1_str.isdigit() and int(col1_str) > 0:
                    circ_num = int(col1_str)
                    circ_nom = str(row[2]).replace("\n", " ").strip() if row[2] else ""
                    stats = extraire_stats(row)
                    # Retrouver et compléter les records CAS A sans nom_circ
                    for rec in reversed(records):
                        if rec["code_circ"] == circ_num and rec["nom_circ"] == "":
                            rec["nom_circ"] = circ_nom
                            break

                # 4. Enregistrement candidat (CAS B inclus)
                if not candidat_valide or not circ_num:
                    continue

                records.append(make_record(
                    region_courante, circ_num, circ_nom,
                    stats, row, a_elu, num_page
                ))

    return pd.DataFrame(records)



def post_traitement(df: pd.DataFrame) -> pd.DataFrame:
    # ── FIX YOPOUGON (circ 047) ───────────────────────────────────────────
    # Supprimer la ligne dupliquée avec mauvaises stats (nb_bv=151)
    mask_yop_faux = (df["code_circ"] == 47) & (df["nb_bv"] == 151)
    df = df[~mask_yop_faux].copy()

    # Corriger toutes les lignes YOPOUGON avec vraies stats PDF p.8
    YOPOUGON_STATS = {
        "nb_bv": 1320, "inscrits": 555901, "votants": 73989,
        "taux_participation": 13.31, "bulletins_nuls": 2055,
        "suf_exprimes": 71934, "blancs_nombre": 707, "blancs_pct": 0.98
    }
    mask_yop = df["code_circ"] == 47
    for col, val in YOPOUGON_STATS.items():
        df.loc[mask_yop, col] = val

    # ── Règle générale : voix > suf_exprimes → circ+1 ──────────────────────
    suf_par_circ = df.groupby("code_circ")["suf_exprimes"].max()
    nom_par_circ = df.groupby("code_circ")["nom_circ"].first()

    for idx, row in df.iterrows():
        suf = suf_par_circ.get(row["code_circ"], 0)
        if row["est_elu"] == "OUI" and suf > 0 and row["voix_obtenues"] > suf:
            circ_dest = row["code_circ"] + 1
            df.at[idx, "code_circ"] = circ_dest
            df.at[idx, "nom_circ"]  = nom_par_circ.get(circ_dest, "")
            for col in ["nb_bv","inscrits","votants","taux_participation",
                        "bulletins_nuls","suf_exprimes","blancs_nombre","blancs_pct"]:
                vals = df[df["code_circ"] == circ_dest][col]
                if not vals.empty:
                    df.at[idx, col] = vals.iloc[0]

    return df
if __name__ == "__main__":
    PDF_PATH    = "data/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf"
    OUTPUT_PATH = "output/resultats_officiels_2025_FINAL.csv"

    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF introuvable : {PDF_PATH}")
        exit(1)

    os.makedirs("output", exist_ok=True)
    print("🚀 Extraction du PDF en cours...")
    df = extraire_donnees_pdf(PDF_PATH)

    nb_regions   = df["region"].nunique()
    nb_circs     = df["code_circ"].nunique()
    nb_candidats = len(df)
    nb_elus      = (df["est_elu"] == "OUI").sum()

    print(f"\n📊 RÉSULTATS D'EXTRACTION :")
    print(f"   Régions          : {nb_regions}")
    print(f"   Circonscriptions : {nb_circs}")
    print(f"   Candidats        : {nb_candidats}")
    print(f"   Élus détectés    : {nb_elus}")

    elus_par_circ = df[df["est_elu"] == "OUI"].groupby("code_circ").size()
    sans_elu  = [c for c in sorted(df["code_circ"].unique()) if c not in elus_par_circ.index]
    multi_elu = elus_par_circ[elus_par_circ > 1]

    if sans_elu:
        print(f"   ⚠️  Circs sans élu   : {sans_elu}")
    if not multi_elu.empty:
        print(f"   ⚠️  Circs multi-élu  : {multi_elu.to_dict()}")
    if not sans_elu and multi_elu.empty and nb_circs == 205 and nb_elus == 205:
        print("   ✅ Validation parfaite : 205 circs, 205 élus, 0 anomalie")

    df = post_traitement(df)

    # Re-valider après post-traitement
    nb_elus2 = (df['est_elu'] == 'OUI').sum()
    elus2 = df[df['est_elu'] == 'OUI'].groupby('code_circ').size()
    sans2 = [c for c in sorted(df['code_circ'].unique()) if c not in elus2.index]
    multi2 = elus2[elus2 > 1]
    if not sans2 and multi2.empty:
        print(f"   ✅ Post-traitement OK : {nb_elus2} élus, 0 anomalie")

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")
    print(f"\n✅ Fichier sauvegardé : {OUTPUT_PATH}")