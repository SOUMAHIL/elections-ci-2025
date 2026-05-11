import pandas as pd
import os
from langchain_community.vectorstores import FAISS
from langchain_mistralai import MistralAIEmbeddings
from langchain_core.documents import Document
from dotenv import load_dotenv
load_dotenv()

def generate_vector_store(api_key):
    df = pd.read_csv("output/resultats_officiels_2025_FINAL.csv")
    documents = []
    for _, row in df.iterrows():
        content = f"""
Dans la circonscription {row['nom_circ']} de la région {row['region']},
le candidat {row['nom_candidat']} du parti {row['parti']}
a obtenu {row['voix_obtenues']} voix.
Statut : {"ÉLU" if row['est_elu']=="OUI" else "NON ÉLU"}.
Participation : {row['taux_participation']}%.
"""
        metadata = {
            "circonscription": row["nom_circ"],
            "region": row["region"],
            "parti": row["parti"]
        }
        documents.append(Document(page_content=content, metadata=metadata))

    print(f"📄 {len(documents)} documents à indexer...")
    embeddings = MistralAIEmbeddings(
        model="mistral-embed",
        mistral_api_key=api_key
    )
    vector_store = FAISS.from_documents(documents, embeddings)
    os.makedirs("data", exist_ok=True)
    vector_store.save_local("data/faiss_index")
    print("✅ FAISS index créé avec Mistral Embeddings")

if __name__ == "__main__":
    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        print("❌ MISTRAL_API_KEY manquante dans .env")
    else:
        generate_vector_store(key)
