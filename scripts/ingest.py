import pdfplumber
import pandas as pd
import json
import re
import os
import unicodedata
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# 1. Chargement de ton dictionnaire (La Vérité)
def load_config():
    with open('data/election_dict.json', 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()
VALID_REGIONS = config['regions']
VALID_CIRCS = config['circonscriptions']

def find_exact_name(id_str, list_circs):
    """Trouve le nom propre de la circonscription dans le JSON via son ID"""
    prefix = f"{id_str} -"
    for c in list_circs:
        if c.startswith(prefix):
            return c
    return f"CIRCONSCRIPTION {id_str}"

def normalize_num(value):
    if value is None or str(value).strip().upper() in ["", "-", "NAN"]: return 0.0
    s = "".join(re.findall(r"[\d,.]+", str(value))).replace(",", ".")
    try: return float(s)
    except: return 0.0

def extract_id_centrique():
    all_data = []
    
    # Variables d'état (la mémoire du script)
    current_region = "INCONNUE"
    current_id = None
    current_circ_name = "INCONNUE"
    # On stocke les stats globales de la ville en cours pour les attribuer aux candidats
    city_stats = {"inscrits": 0, "votants": 0}

    log.info("🚀 Démarrage de l'extraction ID-Centrique...")
    
    with pdfplumber.open("data/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf") as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            if not table: continue

            for row in table:
                # 1. DETECTION DE LA REGION (Colonne 0)
                # Si on lit une région connue, on met à jour
                reg_raw = str(row[0]).strip().replace("\n", "")
                for r in VALID_REGIONS:
                    if r.replace("-","") in reg_raw.replace("-","").upper():
                        current_region = r
                        break

                # 2. DETECTION DU CHANGEMENT DE VILLE (L'ID est le Patron)
                id_raw = str(row[1]).strip()
                if id_raw.isdigit() and len(id_raw) <= 3:
                    new_id = id_raw.zfill(3)
                    
                    # Si l'ID change, on réinitialise les stats de la ville
                    if new_id != current_id:
                        current_id = new_id
                        current_circ_name = find_exact_name(current_id, VALID_CIRCS)
                        # On capture les nouvelles stats sur cette ligne
                        city_stats["inscrits"] = normalize_num(row[4])
                        city_stats["votants"] = normalize_num(row[5])
                        log.info(f"📍 Passage à la circonscription : {current_id}")

                # 3. CAPTURE DES CANDIDATS (Colonne 12)
                cand_name = str(row[12]).replace("\n", " ").strip().upper()
                if not cand_name or cand_name in ["", "NAN", "CANDIDATS / LISTES DE CANDIDATS"]:
                    continue
                
                # On ignore les lignes de bruit technique
                if len(cand_name) < 3 or "TOTAL" in cand_name: continue

                # On ajoute la ligne
                all_data.append({
                    "Region": current_region,
                    "ID_Circ": current_id,
                    "Circonscription": current_circ_name,
                    "Inscrits": city_stats["inscrits"],
                    "Votants": city_stats["votants"],
                    "Parti": str(row[11]).replace("\n", " ").strip().upper(),
                    "Candidat": cand_name,
                    "Score": normalize_num(row[13]),
                    "Elu_Brut": str(row[15]).upper()
                })
                
                # Une fois qu'on a attribué les stats au premier candidat, 
                # on les met à 0 pour les suivants du même bloc (Règle SUM SQL)
                city_stats["inscrits"] = 0
                city_stats["votants"] = 0

    df = pd.DataFrame(all_data)

    # 4. ARBITRAGE FINAL DES ELUS (Un seul OUI par ID_Circ)
    log.info("🏆 Arbitrage final des vainqueurs...")
    df['Elu'] = "NON"
    # Pour chaque ID, on trouve la ligne qui a le Score maximum
    # idxmax() renvoie l'index de la ligne
    idx_winners = df.groupby('ID_Circ')['Score'].idxmax()
    df.loc[idx_winners, 'Elu'] = "OUI"
    
    # Sécurité : si le score est 0, personne n'est élu
    df.loc[df['Score'] == 0, 'Elu'] = "NON"

    return df

if __name__ == "__main__":
    try:
        final_df = extract_id_centrique()
        os.makedirs("output", exist_ok=True)
        final_df.to_csv("output/resultats_officiels_2025_FINAL.csv", index=False)
        log.info(f"✅ Terminé ! CSV généré avec {len(final_df)} lignes.")
    except Exception as e:
        log.error(f"❌ Erreur : {e}")