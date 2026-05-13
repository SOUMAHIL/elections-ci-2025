"""
semantic_memory.py
==================
Mémoire sémantique de l'agent — stocke et retrouve les échanges passés
via un index FAISS dédié (séparé de data/faiss_index/).

Utilisation dans app.py :
    from scripts.semantic_memory import SemanticMemory
    memory = SemanticMemory(api_key)

    # Avant Mistral → chercher un souvenir similaire
    contexte = memory.search(question)

    # Après la réponse → sauvegarder l'échange
    memory.save(question, reponse)

LOGIQUE DES SEUILS (distance L2 — plus petit = plus similaire) :
    distance < 0.30 → doublon exact      → on ne sauvegarde pas
    distance < 0.50 → question similaire → on injecte dans le prompt
    distance >= 0.50 → question différente → on ignore
"""

import time
from pathlib import Path

# ── Chemin de stockage de l'index sémantique ─────────────────────────────────
MEMORY_DIR = Path("memory/semantic_index")

# ── Seuils basés sur la distance L2 FAISS ────────────────────────────────────
SEUIL_DOUBLON   = 0.30   # en dessous → doublon, on ne sauvegarde pas
SEUIL_RECHERCHE = 0.50   # en dessous → question similaire, on injecte le contexte

# ── Nombre maximum de souvenirs à injecter dans le prompt ────────────────────
MAX_MEMORIES_IN_CONTEXT = 2


class SemanticMemory:

    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.index    = None
        self.is_ready = False

        try:
            from langchain_mistralai import MistralAIEmbeddings
            from langchain_community.vectorstores import FAISS

            self.embeddings = MistralAIEmbeddings(
                model="mistral-embed",
                mistral_api_key=api_key,
            )
            self.FAISS = FAISS

            if (MEMORY_DIR / "index.faiss").exists():
                self.index = FAISS.load_local(
                    str(MEMORY_DIR),
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
                print(f"✅ Mémoire sémantique chargée ({self._count()} souvenirs)")
            else:
                print("📭 Mémoire sémantique vide — sera créée au premier échange")

            self.is_ready = True

        except Exception as e:
            print(f"⚠️ Mémoire sémantique non disponible : {e}")
            self.is_ready = False

    def _count(self) -> int:
        if self.index is None:
            return 0
        try:
            return self.index.index.ntotal
        except Exception:
            return 0

    def save(self, question: str, reponse: str) -> bool:
        if not self.is_ready:
            return False
        if not reponse or len(reponse.strip()) < 20:
            return False
        if "refusée" in reponse.lower() or "guardrail" in reponse.lower():
            return False

        # ── Dédoublonnage par distance L2 ────────────────────────────
        if self.index is not None and self._count() > 0:
            try:
                resultats = self.index.similarity_search_with_score(question, k=1)
                if resultats:
                    _, distance = resultats[0]
                    if distance < SEUIL_DOUBLON:
                        print(f"⏭️  Doublon détecté (distance {distance:.4f}) — non sauvegardé")
                        return False
            except Exception:
                pass

        try:
            texte_complet = f"Question : {question}\nRéponse : {reponse[:500]}"
            metadata = {
                "question":  question,
                "reponse":   reponse[:500],
                "timestamp": int(time.time()),
            }

            from langchain_core.documents import Document
            doc = Document(page_content=texte_complet, metadata=metadata)

            MEMORY_DIR.mkdir(parents=True, exist_ok=True)

            if self.index is None:
                self.index = self.FAISS.from_documents([doc], self.embeddings)
            else:
                self.index.add_documents([doc])

            self.index.save_local(str(MEMORY_DIR))
            print(f"💾 Souvenir sauvegardé ({self._count()} au total)")
            return True

        except Exception as e:
            print(f"⚠️ Erreur sauvegarde mémoire : {e}")
            return False

    def search(self, question: str) -> str:
        if not self.is_ready or self.index is None or self._count() == 0:
            return ""

        try:
            resultats = self.index.similarity_search_with_score(
                question,
                k=MAX_MEMORIES_IN_CONTEXT,
            )

            souvenirs_pertinents = []
            for doc, distance in resultats:
                if distance < SEUIL_RECHERCHE:
                    q_passee = doc.metadata.get("question", "")
                    r_passee = doc.metadata.get("reponse", "")
                    souvenirs_pertinents.append((q_passee, r_passee, distance))

            if not souvenirs_pertinents:
                return ""

            # Trier par distance croissante (plus similaire en premier)
            souvenirs_pertinents.sort(key=lambda x: x[2])

            contexte = "CONTEXTE MÉMOIRE (échanges similaires passés) :\n"
            for q, r, dist in souvenirs_pertinents:
                contexte += f"- Q: {q}\n  R: {r[:300]}\n"

            print(f"🧠 {len(souvenirs_pertinents)} souvenir(s) trouvé(s) "
                  f"(distance min: {souvenirs_pertinents[0][2]:.4f})")
            return contexte

        except Exception as e:
            print(f"⚠️ Erreur recherche mémoire : {e}")
            return ""

    def reset(self) -> bool:
        try:
            import shutil
            if MEMORY_DIR.exists():
                shutil.rmtree(MEMORY_DIR)
            self.index = None
            print("🗑️ Mémoire sémantique effacée")
            return True
        except Exception as e:
            print(f"⚠️ Erreur reset mémoire : {e}")
            return False

    def stats(self) -> dict:
        return {
            "nb_souvenirs": self._count(),
            "is_ready":     self.is_ready,
            "index_path":   str(MEMORY_DIR),
        }