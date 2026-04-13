import pandas as pd
import json
import os

def build_election_dict():
    # Chemins absolus pour éviter les erreurs de dossier
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, "output", "resultats_officiels_2025_FINAL.csv")
    json_path = os.path.join(base_dir, "data", "election_dict.json")

    if not os.path.exists(csv_path):
        print(f"❌ Erreur : Le fichier CSV est introuvable ici : {csv_path}")
        return

    df = pd.read_csv(csv_path)

    # Création du dictionnaire avec les bons noms de clés pour ton Router
    # ATTENTION : Ton router cherche "regions", "circonscriptions" et "partis" (au pluriel)
    dictionary = {
        "regions": df["Region"].dropna().unique().tolist(),
        "circonscriptions": df["Circonscription"].dropna().unique().tolist(),
        "partis": df["Parti"].dropna().unique().tolist()
    }

    # Sauvegarde au BON endroit avec le BON nom
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=4)

    print(f"✅ SUCCÈS : Le dictionnaire a été créé ici : {json_path}")
    print(f"📊 Statistiques : {len(dictionary['regions'])} régions, {len(dictionary['circonscriptions'])} circonscriptions.")

if __name__ == "__main__":
    build_election_dict()