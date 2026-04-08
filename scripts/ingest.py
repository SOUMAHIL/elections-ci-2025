import pdfplumber
import pandas as pd
import os
import re

# création d'une fonction pour corriger les noms de régions à partir du texte brut extrait du PDF
def corriger_nom_region(nom_brut):
    #Si la valeur est vide, Tu arrêtes directement et tu renvoies None
    if not nom_brut: return None
    # On nettoie tout (tu t’assures que c’est du texte,enlève les retours à la ligne,enlève les espaces,enlève les tirets,met tout en MAJUSCULE )
    n = str(nom_brut).replace("\n", "").replace(" ", "").replace("-", "").upper() 
    
    # Dictionnaire complet des régions ivoiriennes (scrambled vs propre)
    corrections = {
        "ASSAITYBENGA": "AGNEBY-TIASSA",
        "NAJDIBA": "DISTRICT AUTONOME D'ABIDJAN",
        "ORKUOSSUOMAYE": "DISTRICT AUTONOME DE YAMOUSSOUKRO",
        "ELKOBG": "GBÔKLÊ", "GBOKLE": "GBÔKLÊ", "EKEBG": "GBÊKÊ",
        "GNIFAB": "BAFING", "EUOGAB": "BAGOUE", "REILEB": "BELIER",
        "EREB": "BERE", "INAKUOB": "BOUNKANI", "YLLAVAC": "CAVALLY",
        "NOLO": "FOLON", "HOG": "GOH", "OGUOTNOG": "GONTOUGO",
        "STNOPSDNARG": "GRANDS-PONTS", "NOMEUG": "GUEMON", "LOBMAH": "HAMBOL",
        "ARDNASSAS": "HAUT-SASSANDRA", "UOFFI": "IFFOU", "NILBAUJD": "INDENIE-DJUABLIN",
        "UOGUODABAK": "KABADOUGOU", "EMAL": "ME", "AUOBJD": "LOH-DIBOUA", 
        "AWAN": "NAWA", "IZN": "N'ZI", "OROP": "PORO", "ORDEP": "SAN-PEDRO", 
        "EOMOC": "SUD-COMOE", "OGOLOHCT": "TCHOLOGO", "IPKNOT": "TONKPI",
        "UOGUODOROW": "WORODOUGOU", "EUOHARAM": "MARAHOUE", "MORONOU": "MORONOU"
    }
    
    # Tu parcours le dictionnaire de corrections, et si tu trouves une faute dans le nom brut, tu renvoies la correction correspondante. Si aucune faute n'est trouvée, tu renvoies None (pour éviter les faux positifs sur les noms de circonscriptions ou les candidats)
    for faute, correction in corrections.items():
        if faute in n: return correction
    return None # Si c'est juste du bruit (A, S, S, I...), on renvoie None

# cette fonction sert à lire un PDF,extraire les tableaux, nettoyer les données, et construire un dataset structuré(dataframe)
def analyser_mon_pdf(pdf_path):
    # tu initialises une liste :
    toutes_les_lignes = [] # <- li
    region_actuelle = "AGNEBY-TIASSA" # <- tu commences avec une région par défaut (la première du PDF) pour éviter les valeurs vides au début
    circ_actuelle = "INCONNUE" # mémoire de la circonscription actuelle, pour éviter les valeurs vides
    # Stats qui persistent VRAIMENT
    # Mémoires des statistiques àa stocke inscrits,votants, taux de participation, bulletins nuls, suffrages exprimés, bulletins blancs en nombre et en pourcentage
    stats_mem = {"ins": "0", "vot": "0", "taux": "0%", "nul": "0", "exp": "0", "b_nom": "0", "b_pct": "0%"}

    # lecture du PDF
    with pdfplumber.open(pdf_path) as pdf: # tu ouvres le PDF avec pdfplumber
        for i, page in enumerate(pdf.pages): # Tu parcours chaque page
            tableau = page.extract_table() # Tu récupères le tableau de la page
            if not tableau: continue # si rien → tu passes à la page suivante

            for ligne in tableau: # tu parcours chaque ligne du tableau
                # 1. RÉGION : On ne change QUE si on reconnaît une région du dictionnaire
                col0 = str(ligne[0]).strip() if ligne[0] else "" # Tu prends la colonne 0 et tu la nettoies (enlève les espaces, les retours à la ligne, etc.)
                n_reg = corriger_nom_region(col0) # Tu essaies de corriger avec ta fonction
                if n_reg: # Si une région est reconnue 
                    region_actuelle = n_reg # Tu mets à jour la région actuelle

                # 2. STATISTIQUES : On ne met à jour QUE si la ligne contient de vrais chiffres
                # On utilise la colonne 4 (Inscrits) comme preuve
                val_ins_brute = "".join(filter(str.isdigit, str(ligne[4]))) if ligne[4] else "" # Tu extrais uniquement les chiffres de la colonne "Inscrits"
                if val_ins_brute and int(val_ins_brute) > 100: # Si c'est un nombre valide et supérieur à 100, on considère que c'est une ligne de statistiques
                   
                   # Tu mets à jour les stats. cela permet d'éviter les lignes vides, les titres et les bruits (A, S, S, I...) qui pourraient apparaître dans les colonnes de stats
                    stats_mem = {
                        "ins": ligne[4], "vot": ligne[5], "taux": ligne[6],
                        "nul": ligne[7], "exp": ligne[8], "b_nom": ligne[9], "b_pct": ligne[10]
                    }

                # 3. CIRCONSCRIPTION : On met à jour si la colonne 1 est un nombre (ex: 006)
                col1 = str(ligne[1]).strip() if ligne[1] else "" # Tu prends la colonne 1 et tu la nettoies
                if col1.isdigit() and len(col1) <= 3: # Si c'est un numéro de circonscription (1 à 3 chiffres), on met à jour la circonscription actuelle
                    nom_c = str(ligne[2]).replace("\n", " ").strip() 
                    circ_actuelle = f"{col1} - {nom_c}" # Tu construis : "006 - BOUAFLE" pour la circonscription actuelle

                # 4. CANDIDAT : extraction du candiadat
                nom_cand = str(ligne[12]).strip() if len(ligne) > 12 and ligne[12] else None # Tu récupères le nom du candidat 
                if nom_cand and nom_cand.upper() not in ["CANDIDATS / LISTES DE CANDIDATS", "TOTAL"]: # tu filtres : titres et lignes inutiles

                    if len(nom_cand) > 3: # # On évite d'ajouter les morceaux de texte vertical (A, S, S...)
                        toutes_les_lignes.append({ # Tu ajoutes un dictionnaire propre
                            "Region": region_actuelle,
                            "Circonscription": circ_actuelle,
                            "Inscrits": stats_mem["ins"], 
                            "Votants": stats_mem["vot"],
                            "Taux_Participation": stats_mem["taux"], 
                            "Bulletins_Nuls": stats_mem["nul"],
                            "Suf_Exprimes": stats_mem["exp"], 
                            "Bull_Blancs_Nombre": stats_mem["b_nom"],
                            "Bull_Blancs_Pct": stats_mem["b_pct"],
                            "Parti": str(ligne[11]).strip() if len(ligne) > 11 and ligne[11] else "IND.",
                            "Candidat": nom_cand.replace("\n", " "),
                            "Score": str(ligne[13]).strip() if len(ligne) > 13 and ligne[13] else "0",
                            "Pourcentage": str(ligne[14]).strip() if len(ligne) > 14 else "",
                            "Elu": "OUI" if (len(ligne) > 15 and "ELU" in str(ligne[15])) else "NON"
                        })

    return pd.DataFrame(toutes_les_lignes) # transformes tout en DataFrame (pandas)

# Exécution principale
if __name__ == "__main__": # Exécuter seulement si tu lances le script directement
    chemin = "data/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf"
    print("Extraction V6 : Nettoyage final et alignement strict...")
    df = analyser_mon_pdf(chemin) # Tu lances ton extraction
    
    # Nettoyage des espaces insécables pour les calculs futurs
    for c in ["Inscrits", "Votants", "Suf_Exprimes", "Score"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.replace(r'\s+', '', regex=True) # Tu enlèves les espaces dans les nombres
            
    df.to_csv("output/resultats_officiels_2025_FINAL.csv", index=False) # Tu sauvegardes en CSV
    print(f"\nExtraction terminée ! {len(df)} candidats alignés correctement.")