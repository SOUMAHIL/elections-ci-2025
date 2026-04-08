import pandas as pd
import os
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

def generate_vector_store(api_key):
    # 1. Charger les données propres du Level 1
    # Assure-toi que le chemin est correct selon ta structure
    df = pd.read_csv("output/resultats_officiels_2025_FINAL.csv")
    
    print("Colonnes détectées :", df.columns.tolist())
    
    # 2. Transformer chaque ligne en texte descriptif (Document)
    documents = []
    for _, row in df.iterrows():
        # Utilisation des noms de colonnes EXACTS affichés par ton terminal

        nom_court = row['Circonscription'].split(',')[0] # Prend juste '202 - BOBI-DIARABANA'
        content = (
            f"CIRCONSCRIPTION : {nom_court}. "
            f"REGION : {row['Region']}. "
            f"RESULTAT : Le candidat {row['Candidat']} du parti {row['Parti']} a obtenu {row['Score']} voix. "
            f"VERDICT : {'VAINQUEUR' if row['Elu'] == 'OUI' else 'NON ELU'}."
        )
        
        # Métadonnées pour les citations (Bonus Level 2)
        metadata = {
            "circonscription": row['Circonscription'],
            "parti": row['Parti'],
            "source": "Résultats Officiels 2025"
        }
        documents.append(Document(page_content=content, metadata=metadata))

    # 3. Créer les Embeddings (Transformation du texte en nombres)
    # 
    embeddings = OpenAIEmbeddings(openai_api_key=api_key)
    
    # 4. Stocker dans une base vectorielle locale (FAISS)
    # FAISS est une base de données de vecteurs ultra-rapide
    vector_store = FAISS.from_documents(documents, embeddings)
    
    # 5. Sauvegarder l'index sur le disque
    if not os.path.exists("data"):
        os.makedirs("data")
        
    vector_store.save_local("data/faiss_index")
    print("✅ Index vectoriel créé avec succès dans data/faiss_index")

if __name__ == "__main__":
    # N'oublie pas de mettre ta clé API ici ou de l'appeler via os.getenv
    key = "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" # Ta clé OpenAI
    generate_vector_store(key)