import pandas as pd
import json
import os

def build_election_dict():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, "output", "resultats_officiels_2025_FINAL.csv")
    json_path = os.path.join(base_dir, "data", "election_dict.json")

    df = pd.read_csv(csv_path)

    dictionary = {
        "regions": df["region"].dropna().unique().tolist(),
        "circonscriptions": df["nom_circ"].dropna().unique().tolist(),
        "partis": df["parti"].dropna().unique().tolist()
    }

    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=4)

    print("✅ Dictionnaire créé")
    print(f"📊 {len(dictionary['regions'])} régions")
    print(f"📊 {len(dictionary['circonscriptions'])} circonscriptions")

if __name__ == "__main__":
    build_election_dict()