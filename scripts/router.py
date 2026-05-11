import os
import json
import re
import time
import duckdb
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_community.vectorstores import FAISS
from scripts.prompts import detecter_injection, GUARDRAIL_RESPONSE

# ── Langfuse v4 ───────────────────────────────────────────────────────────────
try:
    from langfuse import Langfuse, observe, get_client
    from dotenv import load_dotenv
    load_dotenv()
    _lf = get_client()
    _lf.auth_check()
    LANGFUSE_OK = True
except Exception:
    def observe(**kw):
        return lambda f: f
    _lf = None
    LANGFUSE_OK = False

# ── Synonymes et expansions de noms de villes / communes ─────────────────────
SYNONYMES = {
    "koumassi": "KOUMASSI, COMMUNE", "yopougon": "YOPOUGON,COMMUNE",
    "cocody": "COCODY, COMMUNE", "abobo": "ABOBO, COMMUNE",
    "adjamé": "ADJAME, COMMUNE", "adjame": "ADJAME, COMMUNE",
    "marcory": "MARCORY, COMMUNE", "plateau": "PLATEAU, COMMUNE",
    "treichville": "TREICHVILLE, COMMUNE", "port-bouet": "PORT-BOUET, COMMUNE",
    "port bouet": "PORT-BOUET, COMMUNE",
    "anyama": "ANYAMA ET BROFODOUME, COMMUNES ET SOUS-PREFECTURES",
    "bingerville": "BINGERVILLE, COMMUNE ET SOUS-PREFECTURE",
    "songon": "SONGON, COMMUNE ET SOUS-PREFECTURE",
    "bouaké": "BOUAKE, VILLE", "bouake": "BOUAKE, VILLE",
    "yamoussoukro": "YAMOUSSOUKRO,COMMUNE", "korhogo": "KORHOGO, VILLE",
    "san pedro": "SAN PEDRO, COMMUNE", "san-pedro": "SAN PEDRO, COMMUNE",
    "tabou": "TABOU",
    "daloa": "DALOA, VILLE ET SOUS-PREFECTURE",
    "abidjan": "DISTRICT AUTONOME D'ABIDJAN",
    "man": "MAN, COMMUNE", "gagnoa": "GAGNOA, COMMUNE",
    "divo": "DIVO, COMMUNE", "agboville": "AGBOVILLE COMMUNE",
    "toumodi": "TOUMODI, COMMUNE",
    "koro": "KORO, COMMUNE ET SOUS-PREFECTURE",
    "boundiali": "BOUNDIALI ET GANAONI, COMMUNES ET SOUS-PREFECTURES",
    "daoukro": "DAOUKRO ET N'GATTAKRO, COMMUNES ET SOUS-PREFECTURES",
    "bondoukou": "APPIMANDOUM, BONDOUKOU ET PINDA-BOROKO, COMMUNES ET SOUS-PREFECTURES",
    "guiglo": "GUIGLO, COMMUNE", "soubré": "SOUBRE, COMMUNES ET SOUS-PREFECTURE",
    "soubre": "SOUBRE, COMMUNES ET SOUS-PREFECTURE",
    "ouangolodougou": "KAOUARA ET OUANGOLODOUGOU, COMMUNES ET SOUS-PREFECTURES",
    "bouaflé": "BOUAFLE, COMMUNE", "bouafle": "BOUAFLE, COMMUNE",
    "lakota": "LAKOTA, COMMUNE ET SOUS-PREFECTURE",
    "grand-bassam": "GRAND-BASSAM, COMMUNE ET SOUS-PREFECTURE",
    "grand bassam": "GRAND-BASSAM, COMMUNE ET SOUS-PREFECTURE",
}

REGIONS_AMBIGUES = {
    "agneby", "agneby-tiassa", "bafing", "bagoue", "belier", "bere",
    "bounkani", "cavally", "folon", "gbeke", "gbêkê", "gbokle", "gbôklê",
    "goh", "gontougo", "grands-ponts", "guemon", "guémon", "hambol",
    "haut-sassandra", "iffou", "indenie-djuablin", "kabadougou", "la me",
    "loh-djiboua", "marahoue", "marahoué", "moronou", "nawa", "n'zi",
    "nzi", "poro", "san-pedro", "sud-comoe", "sud-comoé", "tchologo",
    "tonkpi", "worodougou", "me", "gbeke", "bagoue", "nawa",
    "gontougo", "iffou", "agboville",
}

# ── Mots trop génériques à exclure lors de l'extraction ──────────────────────
MOTS_EXCLUS = {
    "commune", "communes", "sous", "prefecture", "prefectures",
    "ville", "district", "autonome", "nord", "sud", "est", "ouest",
    "pour", "les", "des", "dans", "avec",
}


class HybridRouter:

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.llm = ChatMistralAI(
            model="mistral-small-latest",
            temperature=0,
            mistral_api_key=api_key,
            timeout=30,
        )
        self.regions = []
        self.circs   = []
        self.partis  = []

        path = "data/election_dict.json"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.regions = d.get("regions", [])
            self.circs   = d.get("circonscriptions", [])
            self.partis  = d.get("partis", [])

        self.ref = [x for x in (self.regions + self.circs + self.partis) if x]

        # ── Chargement dynamique des mots-clés depuis la DB ──────────
        self.mots_circs = self._charger_mots_circs()
        print(f"✅ {len(self.mots_circs)} mots-circs chargés depuis la DB")

        # ── FAISS activé avec Mistral Embeddings ─────────────────────
        try:
            embeddings = MistralAIEmbeddings(
                model="mistral-embed",
                mistral_api_key=api_key
            )
            self.vector_store = FAISS.load_local(
                "data/faiss_index",
                embeddings,
                allow_dangerous_deserialization=True
            )
            print("✅ FAISS chargé avec Mistral Embeddings")
        except Exception as e:
            print(f"⚠️ FAISS non disponible : {e}")
            self.vector_store = None

    # ── CHARGEMENT MOTS-CIRCS DEPUIS LA DB ───────────────────────────
    def _charger_mots_circs(self) -> list:
        """
        Extrait dynamiquement les mots-clés significatifs des noms de circs
        depuis la DB. Gère les tirets composés (KOUN-FAO → kounfao)
        et les caractères spéciaux (point médian ·).
        """
        try:
            with duckdb.connect("data/elections_ci.db") as conn:
                df = conn.execute(
                    "SELECT DISTINCT nom_circ FROM circonscriptions"
                ).df()
        except Exception as e:
            print(f"⚠️ Impossible de charger les mots-circs : {e}")
            return []

        mots = set()
        for nom in df["nom_circ"]:
            # 1. Normaliser les caractères spéciaux
            nom_clean = nom.lower()
            nom_clean = nom_clean.replace("·", " ")   # point médian → espace
            nom_clean = nom_clean.replace("'", " ")   # apostrophe → espace

            # 2. Mots avec tirets : garder la version collée (plus distinctive)
            #    Ex: "koun-fao" → "kounfao", "port-bouet" → "portbouet"
            parties_tiret = re.findall(r'[a-zA-ZÀ-ÿ]+(?:-[a-zA-ZÀ-ÿ]+)+', nom_clean)
            for partie in parties_tiret:
                colle = partie.replace("-", "")
                if len(colle) >= 5 and colle not in MOTS_EXCLUS:
                    mots.add(colle)

            # 3. Mots simples de 5+ lettres
            nom_sans_tiret = nom_clean.replace("-", " ")
            for mot in re.findall(r'[a-zA-ZÀ-ÿ]{5,}', nom_sans_tiret):
                if mot not in MOTS_EXCLUS:
                    mots.add(mot)

        return sorted(mots)

    # ── HELPERS LANGFUSE v4 ───────────────────────────────────────────
    def _score(self, trace_id, name, value, comment=""):
        if not LANGFUSE_OK or not trace_id or not _lf:
            return
        try:
            _lf.create_score(trace_id=trace_id, name=name, value=value, comment=comment)
        except Exception:
            pass

    def _flush(self):
        if LANGFUSE_OK and _lf:
            try:
                _lf.flush()
            except Exception:
                pass

    def _get_trace_id(self):
        if not LANGFUSE_OK or not _lf:
            return None
        try:
            return _lf.get_current_trace_id()
        except Exception:
            return None

    def _update_trace(self, **kwargs):
        if not LANGFUSE_OK or not _lf:
            return
        try:
            _lf.set_current_trace_io(**kwargs)
        except Exception:
            pass

    # ── NORMALISATION ─────────────────────────────────────────────────
    def normalize_query(self, query: str) -> str:
        q_lower = query.lower()
        for alias, nom_complet in SYNONYMES.items():
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, q_lower):
                query = re.sub(pattern, nom_complet, query, flags=re.IGNORECASE)
                break
        return query

    def est_question_ambigue(self, query: str) -> bool:
        q = query.lower().strip()
        mots_precision = [
            "commune", "sous-préfecture", "circonscription", "circ",
            "candidat", "élu", "taux", "score", "voix", "gagnant",
            "parti", "pourcentage", "top", "nombre", "combien",
            "résultats dans", "résultat dans", "dans la région",
        ]
        questions_trop_vagues = [
            "qui a gagné", "qui a gagné ?", "qui gagne",
            "quel est le gagnant", "qui est l'élu", "qui a remporté"
        ]
        if any(q.strip().rstrip('?') == v.rstrip('?') for v in questions_trop_vagues):
            return True
        if any(m in q for m in mots_precision):
            return False
        if re.search(r'résultats?\s+dans\s+(la\s+)?région', q):
            return False
        q_clean = re.sub(r'résultats?\s*(pour|de|en|sur)?\s*', '', q).strip()
        q_clean = re.sub(r'(la\s+)?(région\s+)?(de\s+)?', '', q_clean).strip()
        q_clean = q_clean.replace('?', '').strip()
        for region in REGIONS_AMBIGUES:
            if q_clean == region.lower() and len(q.split()) <= 4:
                return True
        if len(q.split()) <= 2:
            return True
        return False

    # ── DÉTECTION LOCALISATION ────────────────────────────────────────
    def contient_localisation(self, query: str) -> bool:
        q = query.lower()
        for alias in SYNONYMES.keys():
            if alias in q:
                return True
        regions_db = [
            "agneby", "bafing", "bagoue", "belier", "bere", "bounkani",
            "cavally", "folon", "gbeke", "gbokle", "goh", "gontougo",
            "grands-ponts", "guemon", "hambol", "haut-sassandra", "iffou",
            "indenie", "kabadougou", "loh-djiboua", "marahoue", "moronou",
            "nawa", "poro", "san-pedro", "sud-comoe", "tchologo", "tonkpi",
            "worodougou", "abidjan", "yamoussoukro", "district",
        ]
        for region in regions_db:
            if region in q:
                return True
        if re.search(r'\b\d{1,3}\b', q) and any(
            w in q for w in ["circ", "circonscription", "numéro"]):
            return True
        if re.search(r'\bà\s+\d{1,3}\b', q):
            return True
        mots_geo = [
            "commune", "sous-préfecture", "sous-prefecture",
            "ville", "district", "région", "region",
            "circ", "circonscription", "préfecture", "prefecture",
            "et sous-pref", "communes et", "sous-prefectures",
        ]
        if any(m in q for m in mots_geo):
            return True
        # Vérifier aussi dans mots_circs chargés dynamiquement
        for mot in self.mots_circs:
            if mot in q:
                return True
        if re.search(r'\b(?:à|de|en|dans)\s+[A-ZÀ-Ü][a-zA-ZÀ-ÿ\-]{3,}', query):
            return True
        return False

    # ── SUGGESTION FAISS ──────────────────────────────────────────────
    def suggerer_localisation(self, query: str) -> str | None:
        if self.vector_store is None:
            return None
        try:
            docs = self.vector_store.similarity_search(query, k=3)
            if docs:
                meta = docs[0].metadata
                circ   = meta.get("circonscription", "")
                region = meta.get("region", "")
                return circ if circ else region
        except Exception as e:
            print(f"FAISS suggestion error: {e}")
        return None

    # ── CLASSIFICATION ────────────────────────────────────────────────
    def classify_intent(self, query: str, callbacks=None) -> str:
        q = query.lower()
        if detecter_injection(query):
            return "BLOCKED"
        salut_mots = ["bonjour", "bonsoir", "que pouvez"]
        salut_mots_courts = ["salut", "hello", "hi"]
        if any(m in q for m in salut_mots) or \
           any(re.search(r'\b' + m + r'\b', q) for m in salut_mots_courts):
            return "GREETING"
        mots_dangereux = [
            "supprime", "supprimer", "efface", "effacer",
            "vider", "détruire", "drop", "delete", "truncate"
        ]
        if any(m in q for m in mots_dangereux):
            return "BLOCKED"
        mots_gagnant = [
            "gagné", "gagnant", "vainqueur", "élu", "remporté",
            "gagne", "champion", "député", "vainqueurs", "élus",
            "qui a remporté", "le gagnant", "le vainqueur",
        ]
        if any(m in q for m in mots_gagnant) and not self.contient_localisation(query):
            return "AMBIGUOUS"
        questions_vagues = [
            "donne moi la circonscription", "donne la circonscription",
            "quelle circonscription", "donne moi le nom",
            "quel est le nom", "donne moi les résultats", "les résultats",
        ]
        q_stripped = q.strip().rstrip("?").strip()
        if any(q_stripped == v or q_stripped.startswith(v) for v in questions_vagues):
            return "AMBIGUOUS"
        mots_sql = [
            "combien", "nombre", "total", "somme", "top", "score",
            "voix", "gagné", "gagne", "gagnant", "élu", "elu", "élue",
            "participation", "inscrits", "votants", "résultat", "resultat",
            "taux", "pourcentage", "classement", "rang", "premier",
            "siège", "circonscription", "parti", "rhdp", "pdci", "fpi",
            "donne", "quel est le", "qui a gagné", "qui est l'élu",
            "a obtenu", "a remporté", "est-il élu", "est-elle élue",
            "bulletins nuls", "suffrages", "inscrits", "bureaux",
            "circonscriptions gagnées", "remporté", "dominant",
            "comparaison", "écart", "différence", "bilan",
            "graphique", "chart", "visualis", "diagramme", "camembert",
            "représentation", "courbe",
        ]
        if any(x in q for x in mots_sql):
            return "SQL"
        mots_rag = [
            "analyse", "explique", "résume", "resume",
            "tendance", "contexte", "pourquoi", "comment",
            "qu'est-ce que", "quest ce que", "définition",
        ]
        if any(x in q for x in mots_rag):
            return "RAG"
        prompt = f"Réponds par un seul mot SQL ou RAG.\nQuestion : {query}\nRéponse :"
        kwargs = {}
        if callbacks:
            kwargs["config"] = {"callbacks": callbacks}
        rep = self.llm.invoke(prompt, **kwargs).content.upper()
        return "SQL" if "SQL" in rep else "RAG"

    # ── RAG SEARCH ────────────────────────────────────────────────────
    def run_rag_search(self, query: str, history=None, callbacks=None,
                       trace_id: str = None) -> str:
        from scripts.prompts import RAG_GLOSSAIRE
        t0 = time.time()
        faiss_context = ""
        if self.vector_store is not None:
            docs = self.vector_store.similarity_search(query, k=4)
            faiss_context = "\n".join([d.page_content for d in docs])
        hist = ""
        if history:
            for msg in history[-3:]:
                role = "Utilisateur" if msg["role"] == "user" else "Assistant"
                hist += f"{role}: {msg['content']}\n"
        contexte_complet = RAG_GLOSSAIRE
        if faiss_context:
            contexte_complet += f"\n\nDONNÉES DU DATASET :\n{faiss_context}"
        prompt = (
            f"Tu es l'assistant expert des élections législatives CI 2025.\n"
            f"Réponds uniquement selon le contexte fourni ci-dessous.\n"
            f"Si la réponse n'est pas dans le contexte : "
            f"'Information non disponible dans le dataset.'\n\n"
            f"CONTEXTE :\n{contexte_complet}\n\n"
            f"{'Historique :' + chr(10) + hist if hist else ''}"
            f"Question : {query}"
        )
        kwargs = {}
        if callbacks:
            kwargs["config"] = {"callbacks": callbacks}
        result = self.llm.invoke(prompt, **kwargs).content
        latency = int((time.time() - t0) * 1000)
        if trace_id:
            self._score(trace_id, "rag-latency-ms", float(latency))
        self._flush()
        return result

    # ── SQL EXECUTION ─────────────────────────────────────────────────
    def executer_sql(self, sql: str):
        class SQLResult:
            def __init__(self, success, data=None, error=""):
                self.success = success
                self.data    = data
                self.error   = error

        forbidden = ["DROP","DELETE","UPDATE","INSERT","ALTER","TRUNCATE","CREATE"]
        for word in forbidden:
            if re.search(r'\b' + word + r'\b', sql.upper()):
                return SQLResult(False, error=f"Opération interdite : {word}")
        if "LIMIT" not in sql.upper():
            sql = sql.strip().rstrip(";") + " LIMIT 50;"
        try:
            with duckdb.connect("data/elections_ci.db") as conn:
                df = conn.execute(sql).df()
            return SQLResult(True, data=df)
        except Exception as e:
            return SQLResult(False, error=str(e))

    # ── LOG SQL RESULT ────────────────────────────────────────────────
    def log_sql_result(self, trace_id, sql, success, rows=0, error="", latency_ms=0):
        if not LANGFUSE_OK or not trace_id or not _lf:
            return
        try:
            self._score(trace_id, "sql-success",
                        value=1.0 if success else 0.0,
                        comment=error if error else f"{rows} ligne(s)")
            self._score(trace_id, "sql-latency-ms", float(latency_ms))
            self._flush()
        except Exception:
            pass

    # ── FINALISER TRACE ───────────────────────────────────────────────
    def finalize_trace(self, trace_id, response, intent, total_latency_ms):
        if not LANGFUSE_OK or not trace_id or not _lf:
            return
        try:
            self._score(trace_id, "route", 1.0, f"{intent} path")
            self._score(trace_id, "total-latency-ms", float(total_latency_ms))
            self._flush()
        except Exception:
            pass

    # ── POINT D'ENTRÉE PRINCIPAL ──────────────────────────────────────
    @observe(name="agent-question")
    def route(self, question: str, history=None, callbacks=None,
              session_id: str = None) -> dict:
        t0 = time.time()
        trace_id = self._get_trace_id()
        if trace_id:
            try:
                _lf.set_current_trace_io(
                    input={"question": question, "session_id": session_id or "unknown"},
                )
            except Exception:
                pass

        clean_q = self.normalize_query(question)
        intent  = self.classify_intent(clean_q, callbacks=callbacks)

        if intent == "BLOCKED":
            latency = int((time.time() - t0) * 1000)
            try:
                _lf.set_current_trace_io(output={"intent": "BLOCKED", "blocked": True}) if LANGFUSE_OK and _lf else None
            except Exception:
                pass
            self._score(trace_id, "guardrail", 0.0, "Bloquée par guardrail")
            self._flush()
            return {"intent": "BLOCKED", "clean_query": clean_q,
                    "response": GUARDRAIL_RESPONSE, "trace_id": trace_id, "latency_ms": latency}

        if intent != "GREETING" and self.est_question_ambigue(clean_q):
            msg = (
                "❓ Votre question est un peu large. Pourriez-vous préciser "
                "la **circonscription** ou le type d'information souhaité ?\n\n"
                "Exemples : *Résultats pour BAGOUE, circonscription 014 ?* ou "
                "*Qui a gagné dans la région BAGOUE ?*"
            )
            latency = int((time.time() - t0) * 1000)
            try:
                _lf.set_current_trace_io(output={"intent": "AMBIGUOUS"}) if LANGFUSE_OK and _lf else None
            except Exception:
                pass
            self._flush()
            return {"intent": "AMBIGUOUS", "clean_query": clean_q,
                    "response": msg, "trace_id": trace_id, "latency_ms": latency}

        if intent == "RAG":
            response = self.run_rag_search(clean_q, history=history,
                                           callbacks=callbacks, trace_id=trace_id)
            latency = int((time.time() - t0) * 1000)
            try:
                _lf.set_current_trace_io(output={"intent": "RAG", "response": response[:300]}) if LANGFUSE_OK and _lf else None
            except Exception:
                pass
            self._score(trace_id, "route", 1.0, "RAG path")
            self._flush()
            return {"intent": "RAG", "clean_query": clean_q,
                    "response": response, "trace_id": trace_id, "latency_ms": latency}

        latency = int((time.time() - t0) * 1000)
        try:
            _lf.set_current_trace_io(output={"intent": intent}) if LANGFUSE_OK and _lf else None
        except Exception:
            pass
        return {"intent": intent, "clean_query": clean_q,
                "response": None, "trace_id": trace_id, "latency_ms": latency}