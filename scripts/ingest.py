import pdfplumber
import pandas as pd
import os
import re

# nettoyer les valeurs numériques pour les convertir en int ou float, en gérant les cas de valeurs manquantes ou mal formatées
def clean_numeric(val):
    """Nettoie les chaînes pour les convertir en nombres exploitables par SQL."""
    if not val or str(val).strip() in ["-", "", "None", "nan"]:
        return 0
    # Suppression des espaces, des %, et normalisation de la virgule
    clean_val = str(val).replace("\s+", "").replace(" ", "").replace("%", "").replace(",", ".")
    try:
        if "." in clean_val:
            return float(clean_val)
        return int(clean_val)
    except:
        return 0

def corriger_nom_region(nom_brut):
    if not nom_brut: return None
    n = str(nom_brut).replace("\n", "").replace(" ", "").replace("-", "").upper() 
    
    corrections = {
        "ASSAITYBENGA": "AGNEBY-TIASSA", "NAJDIBA": "DISTRICT AUTONOME D'ABIDJAN",
        "ORKUOSSUOMAYE": "DISTRICT AUTONOME DE YAMOUSSOUKRO", "ELKOBG": "GBÔKLÊ", 
        "GBOKLE": "GBÔKLÊ", "EKEBG": "GBÊKÊ", "GNIFAB": "BAFING", "EUOGAB": "BAGOUE", 
        "REILEB": "BELIER", "EREB": "BERE", "INAKUOB": "BOUNKANI", "YLLAVAC": "CAVALLY",
        "NOLO": "FOLON", "HOG": "GOH", "OGUOTNOG": "GONTOUGO", "STNOPSDNARG": "GRANDS-PONTS", 
        "NOMEUG": "GUEMON", "LOBMAH": "HAMBOL", "ARDNASSAS": "HAUT-SASSANDRA", "UOFFI": "IFFOU", 
        "NILBAUJD": "INDENIE-DJUABLIN", "UOGUODABAK": "KABADOUGOU", "EMAL": "ME", 
        "AUOBJD": "LOH-DIBOUA", "AWAN": "NAWA", "IZN": "N'ZI", "OROP": "PORO", 
        "ORDEP": "SAN-PEDRO", "EOMOC": "SUD-COMOE", "OGOLOHCT": "TCHOLOGO", 
        "IPKNOT": "TONKPI", "UOGUODOROW": "WORODOUGOU", "EUOHARAM": "MARAHOUE", "MORONOU": "MORONOU"
    }
    for faute, correction in corrections.items():
        if faute in n: return correction
    return None

def analyser_mon_pdf(pdf_path):
    toutes_les_lignes = []
    region_actuelle = "INCONNUE"
    circ_actuelle = "INCONNUE"
    stats_mem = {"nb_bv": 0, "ins": 0, "vot": 0, "taux": 0, "nul": 0, "exp": 0, "b_nom": 0, "b_pct": 0}
    
    circ_deja_vues = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tableau = page.extract_table()
            if not tableau: continue

            for ligne in tableau:
                # 1. RÉGION
                col0 = str(ligne[0]).strip() if ligne[0] else ""
                n_reg = corriger_nom_region(col0)
                if n_reg: region_actuelle = n_reg

                # 2. STATISTIQUES (Colonnes 3 à 10 désormais)
                # On détecte une ligne de stats si la col 4 (Inscrits) contient un nombre
                val_ins_brute = "".join(filter(str.isdigit, str(ligne[4]))) if ligne[4] else ""
                if val_ins_brute and int(val_ins_brute) > 50:
                    stats_mem = {
                        "nb_bv": clean_numeric(ligne[3]),
                        "ins": clean_numeric(ligne[4]), 
                        "vot": clean_numeric(ligne[5]), 
                        "taux": clean_numeric(ligne[6]), 
                        "nul": clean_numeric(ligne[7]), 
                        "exp": clean_numeric(ligne[8]), 
                        "b_nom": clean_numeric(ligne[9]), 
                        "b_pct": clean_numeric(ligne[10])
                    }

                # 3. CIRCONSCRIPTION
                col1 = str(ligne[1]).strip() if ligne[1] else ""
                if col1.isdigit() and len(col1) <= 3:
                    nom_c = str(ligne[2]).replace("\n", " ").strip()
                    circ_actuelle = f"{col1.zfill(3)} - {nom_c}"

                # 4. CANDIDAT
                nom_cand = str(ligne[12]).strip() if len(ligne) > 12 and ligne[12] else None
                if nom_cand and nom_cand.upper() not in ["CANDIDATS / LISTES DE CANDIDATS", "TOTAL", "TOTAL GENERAL"]:
                    if len(nom_cand) > 3:
                        
                        est_premiere_apparition = circ_actuelle not in circ_deja_vues
                        
                        toutes_les_lignes.append({
                            "Region": region_actuelle,
                            "Circonscription": circ_actuelle,
                            "NB_BV": stats_mem["nb_bv"] if est_premiere_apparition else 0,
                            "Inscrits": stats_mem["ins"] if est_premiere_apparition else 0,
                            "Votants": stats_mem["vot"] if est_premiere_apparition else 0,
                            "Taux_Participation": stats_mem["taux"] if est_premiere_apparition else 0,
                            "Bulletins_Nuls": stats_mem["nul"] if est_premiere_apparition else 0,
                            "Suf_Exprimes": stats_mem["exp"] if est_premiere_apparition else 0,
                            "Bull_Blancs_Nombre": stats_mem["b_nom"] if est_premiere_apparition else 0,
                            "Bull_Blancs_Pct": stats_mem["b_pct"] if est_premiere_apparition else 0,
                            "Parti": str(ligne[11]).strip() if len(ligne) > 11 and ligne[11] else "IND.",
                            "Candidat": nom_cand.replace("\n", " "),
                            "Score": clean_numeric(ligne[13]),
                            "Pourcentage": clean_numeric(ligne[14]),
                            "Elu": "OUI" if (len(ligne) > 15 and "ELU" in str(ligne[15]).upper()) else "NON"
                        })
                        
                        if est_premiere_apparition:
                            circ_deja_vues.add(circ_actuelle)

    return pd.DataFrame(toutes_les_lignes)

if __name__ == "__main__":
    chemin = "data/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf"
    print("🚀 Démarrage de l'Extraction V8 (Full-Schema & Anti-Doublons)...")
    df = analyser_mon_pdf(chemin)
    
    os.makedirs("output", exist_ok=True)
    df.to_csv("output/resultats_officiels_2025_FINAL.csv", index=False)
    
    print(f"✅ Terminé ! {len(df)} lignes extraites avec en-têtes complets.")
