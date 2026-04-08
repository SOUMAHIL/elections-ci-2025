import pandas as pd
import json
import os

def build_election_dict():
    df = pd.read_csv("output/resultats_officiels_2025_FINAL.csv")

    # On récupère les valeurs uniques 
    dictionnary = {
        "regions": df["Region"].unique().tolist(),
        "circonscription": df["Circonscription"].unique().tolist(),
        "parti": df["Parti"].unique().tolist()
    }

    # On sauvegarde pour que l'app puisse le lire
    os.makedirs("output", exist_ok=True)
    with open("data/elections_ci.db", "w", encoding="utf-8") as f:
         json.dump(dictionnary, f, ensure_ascii=False, indent=4)

    print("Dictionnaire de normalisation créé dans data/election_dict.json")

if __name__ == "__main__":
    build_election_dict()
       