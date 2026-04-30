import time
import streamlit as st
import duckdb
import re
import io
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from langfuse.langchain import CallbackHandler

from scripts.router import HybridRouter
from scripts.prompts import (
    SQL_SYSTEM_PROMPT, FINAL_ANSWER_PROMPT,
    CLARIFICATION_PROMPT, GUARDRAIL_RESPONSE, detecter_injection,
)

load_dotenv()
# Streamlit Cloud — lire depuis st.secrets si disponible
import os
if hasattr(st, 'secrets'):
    for key in ['MISTRAL_API_KEY', 'LANGFUSE_PUBLIC_KEY',
                'LANGFUSE_SECRET_KEY', 'LANGFUSE_HOST']:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]

st.set_page_config(
    page_title="IA Élections CI 2025",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] { background: #FAFAFA !important; border-right: 0.5px solid #E8E7E0; }
[data-testid="stSidebar"] .stMarkdown p { font-size: 13px; color: #666; margin: 0; }
[data-testid="stMetric"] {
    background: #F3F2EC !important; border-radius: 10px !important;
    padding: 10px 14px !important; border: 0.5px solid #E0DFD8 !important;
}
[data-testid="stMetricLabel"]  { font-size: 11px !important; color: #888 !important; }
[data-testid="stMetricValue"]  { font-size: 22px !important; font-weight: 500 !important; }
[data-testid="stChatMessage"] {
    border-radius: 12px !important; border: 0.5px solid #EBEBEB !important;
    padding: 12px 16px !important; margin-bottom: 4px !important;
}
[data-testid="stChatInput"] textarea {
    border-radius: 24px !important; background: #F5F4EE !important;
    border: 0.5px solid #D4D3CC !important; font-size: 14px !important;
    padding: 12px 18px !important;
}
[data-testid="stDataFrame"] { border-radius: 10px !important; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "data/elections_ci.db"

for k, v in [("messages", []), ("pending_clarification", False),
              ("options", []), ("session_id", f"web-{int(time.time())}")]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🗳️ Élections CI 2025")
    st.caption("CEI — Scrutin 27 Décembre 2025")
    st.divider()

    try:
        with duckdb.connect(DB_PATH) as _c:
            nb_circs     = _c.execute("SELECT COUNT(DISTINCT code_circ) FROM circonscriptions").fetchone()[0]
            nb_candidats = _c.execute("SELECT COUNT(*) FROM resultats").fetchone()[0]
            taux_moy     = _c.execute(
                "SELECT ROUND(AVG(nb_votants*100.0/NULLIF(nb_inscrits,0)),1) FROM circonscriptions"
            ).fetchone()[0]
    except Exception:
        nb_circs, nb_candidats, taux_moy = 205, "—", "—"

    col1, col2 = st.columns(2)
    col1.metric("Circonscriptions", nb_circs)
    col2.metric("Candidats", f"{nb_candidats:,}".replace(",", " ") if isinstance(nb_candidats, int) else nb_candidats)
    st.metric("Taux de participation moyen", f"{taux_moy}%" if taux_moy != "—" else "—")

    st.divider()

    # ── Partis avec résultats réels ──────────────────────────────────────────
    st.markdown("**Résultats par parti**")
    st.markdown("""
<div style="display:flex;flex-direction:column;gap:5px;margin-top:6px;font-size:12px">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#E85D04;flex-shrink:0"></div>
      <span>RHDP</span>
    </div>
    <span style="font-weight:600;color:#E85D04">155 sièges</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#1D6FA4;flex-shrink:0"></div>
      <span>PDCI-RDA</span>
    </div>
    <span style="font-weight:600;color:#1D6FA4">25 sièges</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#7B5EA7;flex-shrink:0"></div>
      <span>Indépendants</span>
    </div>
    <span style="font-weight:600;color:#7B5EA7">22 sièges</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#2D9A27;flex-shrink:0"></div>
      <span>FPI</span>
    </div>
    <span style="font-weight:600;color:#2D9A27">1 siège</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#C77D29;flex-shrink:0"></div>
      <span>LE BUFFLE</span>
    </div>
    <span style="font-weight:600;color:#C77D29">1 siège</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#888888;flex-shrink:0"></div>
      <span>UNPR</span>
    </div>
    <span style="font-weight:600;color:#888">1 siège</span>
  </div>
  <div style="margin-top:4px;font-size:11px;color:#999">
    Autres partis : ADCI, CODE, MGC, GP-PAIX, EDS et 30+ autres
  </div>
</div>
""", unsafe_allow_html=True)

    st.divider()
    api_key = st.text_input("🔑 Clé API Mistral", type="password", placeholder="...")

    if st.button("🗑️ Effacer la conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ── HEADER ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:4px">
  <div style="font-size:28px">🗳️</div>
  <div>
    <h2 style="margin:0;font-size:22px;font-weight:500">Assistant IA — Élections CI 2025</h2>
    <p style="margin:0;font-size:13px;color:#888">Source : PDF officiel CEI · Scrutin du 27 décembre 2025</p>
  </div>
</div>
""", unsafe_allow_html=True)
st.divider()


def validate_sql(sql):
    return not any(w in sql.upper() for w in
                   ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"])


def construire_historique_ctx(messages, nb_echanges=3):
    if not messages:
        return ""
    msgs_recents = messages[-(nb_echanges * 2):]
    ctx = ""
    for msg in msgs_recents:
        if msg["role"] == "user":
            ctx += f"Utilisateur: {msg['content'][:200]}\n"
        else:
            contenu = msg.get("content", "")[:200] if msg.get("content") else ""
            if contenu:
                ctx += f"Assistant: {contenu}\n"
    return ctx.strip()


def generer_graphique(df, question: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from matplotlib import rcParams

        rcParams.update({
            "font.family": "DejaVu Sans",
            "axes.spines.top": False, "axes.spines.right": False,
            "axes.grid": True, "grid.alpha": 0.25, "grid.linestyle": "--",
        })

        q        = question.lower()
        num_cols = [c for c in df.columns if df[c].dtype in ["int64","float64","int32","float32"]]
        str_cols = [c for c in df.columns if df[c].dtype == "object"]
        if not num_cols:
            return None

        y_col = (next((c for c in num_cols if "voix" in c.lower()), None)
                 or next((c for c in num_cols if "pct" in c.lower() or "taux" in c.lower()), None)
                 or num_cols[0])
        x_col  = str_cols[0] if str_cols else df.columns[0]
        values = df[y_col].values
        if len(values) == 0:
            return None

        def detect_parti_col():
            for c in str_cols:
                if "parti" in c.lower() or "party" in c.lower():
                    return c
            return None

        parti_col = detect_parti_col()

        def clean_label(s, maxlen=24):
            s = str(s).strip()
            slogans = ["UNE COTE DIVOIRE EN PAIX","TOUS ENSEMBLE POUR",
                       "UNE CÔTE D'IVOIRE","UNE CÔTE DIVOIRE",
                       "OSONS LE CHANGEMENT","ENSEMBLE POUR LE","POUR LA NATION"]
            s_up = s.upper()
            for sl in slogans:
                if sl in s_up:
                    idx = s_up.index(sl)
                    prefix = s[:idx].strip(" ,()-")
                    if len(prefix) >= 3:
                        return (prefix[:maxlen] + "…") if len(prefix) > maxlen else prefix
            return (s.upper()[:maxlen] + "…") if len(s) > maxlen else s.upper()

        if parti_col and parti_col != x_col:
            labels_parti = [str(v) for v in df[parti_col]]
            labels = labels_parti if max(len(l) for l in labels_parti) <= 20 else [clean_label(v) for v in df[x_col]]
        else:
            labels = [clean_label(v) for v in df[x_col]]

        def titre_intelligent(q):
            q = re.sub(r'(?i)donne[- ]?moi\s+', '', q)
            q = re.sub(r'(?i)\s+et\s+génère[- ]?moi\s+(un\s+)?(graphique|chart|diagramme)[s]?\s*[?!]*$', '', q)
            q = re.sub(r'(?i)\s+et\s+(un\s+)?(graphique|chart|visualis\w+)\s*[?!]*$', '', q)
            q = re.sub(r'[?!]+$', '', q).strip()
            q = re.sub(r'\s+', ' ', q).strip()
            if q and q[0].islower():
                q = q[0].upper() + q[1:]
            return (q[:68] + "…") if len(q) > 68 else q

        COULEURS_PARTIS = {
            "RHDP":"#E85D04","PDCI":"#1D6FA4","FPI":"#2D9A27",
            "INDEPENDANT":"#7B5EA7","ADCI":"#C77D29","CODE":"#888888",
            "MGC":"#D4A017","EDS":"#4682B4","GP-PAIX":"#20B2AA",
            "LE BUFFLE":"#8B4513","UNPR":"#4B0082",
        }
        def couleur_parti(label):
            l = label.upper()
            for parti, col in COULEURS_PARTIS.items():
                if parti in l: return col
            return None

        est_taux = any(w in q for w in ["taux","participation","pourcentage","%"]) or "taux" in y_col.lower()
        est_top  = any(w in q for w in ["top","classement","plus de voix","rang","premier"])
        est_vert = est_taux or (len(df) <= 4 and not est_top)
        n        = len(values)

        h = max(4.5, min(7, 3 + n * 0.6))
        w = 10 if not est_vert else 9
        fig, ax = plt.subplots(figsize=(w, h))
        fig.patch.set_facecolor("#FAFAFA")
        ax.set_facecolor("#FAFAFA")

        if not est_vert:
            couleurs = []
            for i, lbl in enumerate(labels):
                c = couleur_parti(lbl)
                if c:
                    couleurs.append(c)
                else:
                    t = i / max(n - 1, 1)
                    r = int(0x4C + t * (0xA8 - 0x4C))
                    g = int(0xAF + t * (0xC8 - 0xAF))
                    b = int(0x50 + t * (0x59 - 0x50))
                    couleurs.append(f"#{r:02X}{g:02X}{b:02X}")

            labels_inv, values_inv, couleurs_inv = labels[::-1], values[::-1], couleurs[::-1]
            bars = ax.barh(labels_inv, values_inv, color=couleurs_inv, height=0.55,
                           edgecolor="white", linewidth=0.8)
            vmax = max(values_inv) if max(values_inv) > 0 else 1
            for bar, val in zip(bars, values_inv):
                ax.text(bar.get_width() + vmax * 0.015,
                        bar.get_y() + bar.get_height() / 2,
                        f"{int(val):,}".replace(",", "\u202f"),
                        va="center", ha="left", fontsize=9, color="#333", fontweight="500")
            ax.set_xlabel("Voix obtenues", fontsize=10, color="#555", labelpad=8)
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(
                lambda x, _: f"{int(x):,}".replace(",", "\u202f")))
            ax.set_xlim(0, vmax * 1.18)
            ax.tick_params(axis="y", labelsize=9)
            ax.tick_params(axis="x", labelsize=8, colors="#666")
            ax.spines["left"].set_visible(False)
            ax.grid(axis="x", alpha=0.2, linestyle="--")
            ax.grid(axis="y", visible=False)
        else:
            couleurs = []
            for i, lbl in enumerate(labels):
                c = couleur_parti(lbl)
                if c:
                    couleurs.append(c + "CC")
                else:
                    t = values[i] / max(values) if max(values) > 0 else 0
                    if est_taux:
                        r = int(0x21 + t * (0xE8 - 0x21))
                        g = int(0x96 + t * (0x5D - 0x96))
                        b = int(0xF3 + t * (0x04 - 0xF3))
                        couleurs.append(f"#{r:02X}{g:02X}{b:02X}")
                    else:
                        couleurs.append("#4C8FA0")

            bars = ax.bar(range(n), values, color=couleurs, width=0.55,
                          edgecolor="white", linewidth=0.8)
            vmax = max(values) if max(values) > 0 else 1
            for bar, val in zip(bars, values):
                label_txt = f"{val:.1f}%" if est_taux else f"{int(val):,}".replace(",", "\u202f")
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + vmax * 0.02,
                        label_txt, ha="center", va="bottom", fontsize=9,
                        fontweight="500", color="#333")
            ax.set_xticks(range(n))
            ax.set_xticklabels(labels, rotation=25 if n > 3 else 0,
                               ha="right" if n > 3 else "center", fontsize=9)
            if est_taux:
                ax.set_ylabel("Taux de participation (%)", fontsize=10, color="#555")
                ax.set_ylim(0, min(110, vmax * 1.2))
            else:
                ax.set_ylabel("Voix", fontsize=10, color="#555")
                ax.set_ylim(0, vmax * 1.2)
                ax.yaxis.set_major_formatter(mticker.FuncFormatter(
                    lambda x, _: f"{int(x):,}".replace(",", "\u202f")))
            ax.grid(axis="y", alpha=0.2, linestyle="--")
            ax.grid(axis="x", visible=False)

        ax.set_title(titre_intelligent(question), fontsize=13, fontweight="bold",
                     color="#1a1a2e", pad=14, loc="left")
        fig.text(0.01, 0.01, "Source : CEI — Élections législatives CI, 27 déc. 2025",
                 fontsize=7, color="#aaa", ha="left")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#ddd")
        ax.spines["bottom"].set_color("#ddd")
        plt.tight_layout(rect=[0, 0.04, 1, 1])

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        buf.seek(0)
        plt.close(fig)
        return buf

    except ImportError:
        return None
    except Exception:
        import traceback; traceback.print_exc()
        return None


# ── SUGGESTIONS ────────────────────────────────────────────────────────────────
SUGGESTIONS = [
    ("🏆 Gagnant à Cocody",      "Qui a gagné à COCODY, COMMUNE dans le District d'Abidjan ?"),
    ("📊 Taux à Korhogo",        "Quel est le taux de participation à KORHOGO, VILLE ?"),
    ("🔝 Top 3 à Bouaké",        "Donne le top 3 des candidats à BOUAKE, VILLE avec graphique"),
    ("🗺️ Région Agneby-Tiassa", "Résultats dans la région AGNEBY-TIASSA ?"),
    ("📈 RHDP vs PDCI",          "Combien de sièges le PDCI-RDA a remporté ?"),
    ("❓ Qu'est-ce que la CEI ?","Qu'est-ce que la CEI ?"),
]

if not st.session_state.messages:
    st.markdown("""
<div style="background:#F5F4EE;border-radius:14px;padding:20px 24px;margin-bottom:16px;border:0.5px solid #E0DFD8">
  <p style="font-size:14px;font-weight:500;margin:0 0 6px">👋 Bienvenue sur l'Assistant IA des Élections CI 2025</p>
  <p style="font-size:13px;color:#666;margin:0">
    Posez vos questions sur les résultats, les candidats, les partis ou les taux de participation.
    Je peux aussi générer des <strong>graphiques</strong> — ajoutez simplement <em>«avec graphique»</em>.
  </p>
</div>
""", unsafe_allow_html=True)
    st.markdown("**Essayez par exemple :**")
    cols = st.columns(3)
    for i, (label, query) in enumerate(SUGGESTIONS):
        if cols[i % 3].button(label, use_container_width=True, key=f"sug_{i}"):
            st.session_state.messages.append({"role": "user", "content": query})
            st.session_state["final_query"] = query
            st.rerun()
    st.markdown("")

# ── HISTORIQUE ─────────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("data") is not None:
            st.dataframe(msg["data"])
        if msg.get("chart") is not None:
            st.image(msg["chart"], use_container_width=True)

# ── INPUT ──────────────────────────────────────────────────────────────────────
user_input    = st.chat_input("Posez votre question sur les élections CI 2025…")
current_query = user_input or st.session_state.pop("final_query", None)

if not current_query or not api_key:
    if not api_key and current_query:
        st.warning("⚠️ Entrez votre clé API Mistral dans la barre latérale.")
    st.stop()

if user_input:
    st.session_state.pending_clarification = False
    st.session_state.options = []
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

# ── TRAITEMENT ─────────────────────────────────────────────────────────────────
t_global_start   = time.time()
langfuse_handler = CallbackHandler()
router           = HybridRouter(api_key)
llm              = ChatMistralAI(
    model="mistral-small-latest",
    temperature=0,
    mistral_api_key=api_key,
    timeout=30,
)

route_result   = router.route(
    current_query,
    history=st.session_state.messages,
    callbacks=[langfuse_handler],
    session_id=st.session_state.get("session_id", "web"),
)
clean_question = route_result["clean_query"]
intent         = route_result["intent"]
trace_id       = route_result.get("trace_id")

veut_graphique = any(w in current_query.lower() for w in
                     ["graphique","graph","chart","visualis","courbe",
                      "diagramme","histogramme","pie","camembert"])

# ── RÉPONSE ────────────────────────────────────────────────────────────────────
with st.chat_message("assistant"):
    response   = ""
    df_save    = None
    chart_save = None

    if intent == "BLOCKED":
        response = GUARDRAIL_RESPONSE
        st.warning(f"🛡️ {response}")

    elif intent == "GREETING":
        response = (
            "👋 **Bonjour !** Je suis l'assistant IA des élections ivoiriennes 2025.\n\n"
            "Je peux répondre à vos questions sur :\n"
            "- 🏆 Les **gagnants** par circonscription\n"
            "- 📊 Les **taux de participation**\n"
            "- 🎯 Les **scores** des candidats et partis\n"
            "- 📈 Des **graphiques** interactifs sur demande\n\n"
            "*Exemple : « Top 3 à Bouaké avec graphique »*"
        )
        st.markdown(response)

    elif intent == "AMBIGUOUS":
        response = route_result["response"]
        st.info(response)

    elif intent == "RAG":
        response = route_result["response"] or router.run_rag_search(
            clean_question,
            history=st.session_state.messages[-3:],
            callbacks=[langfuse_handler],
            trace_id=trace_id,
        )
        st.markdown(response)

    elif intent == "SQL":
        # ⚠️ Fast handler DÉSACTIVÉ — trop imprécis
        with st.status("🔍 Analyse SQL...", state="running") as status:
            try:
                t_sql_start = time.time()

                def llm_call_with_retry(prompt, max_retries=3):
                    for attempt in range(max_retries):
                        try:
                            return llm.invoke(
                                prompt,
                                config={"callbacks": [langfuse_handler]},
                            ).content
                        except Exception as e:
                            msg_e = str(e)
                            if "429" in msg_e or "rate_limit" in msg_e.lower():
                                wait = (attempt + 1) * 2
                                st.warning(f"⏳ Limite API atteinte, nouvelle tentative dans {wait}s…")
                                time.sleep(wait)
                            else:
                                raise
                    raise Exception("Rate limit persistant après 3 tentatives.")

                # Historique conversationnel pour questions de suivi
                historique_ctx = construire_historique_ctx(st.session_state.messages)
                prompt_sql = f"{SQL_SYSTEM_PROMPT}\n\n"
                if historique_ctx:
                    prompt_sql += f"HISTORIQUE RÉCENT :\n{historique_ctx}\n\n"
                prompt_sql += f"Question actuelle : {clean_question}"

                sql_raw   = llm_call_with_retry(prompt_sql)
                match     = re.search(r"(SELECT|WITH).*?;", sql_raw, re.DOTALL | re.IGNORECASE)
                sql_clean = re.sub(r"```sql|```", "",
                                   match.group(0) if match else sql_raw).strip()
                st.code(sql_clean, language="sql")

                if validate_sql(sql_clean):
                    sql_result  = router.executer_sql(sql_clean)
                    sql_latency = int((time.time() - t_sql_start) * 1000)

                    router.log_sql_result(
                        trace_id=trace_id,
                        sql=sql_clean,
                        success=sql_result.success,
                        rows=len(sql_result.data) if sql_result.success and sql_result.data is not None else 0,
                        error=sql_result.error if not sql_result.success else "",
                        latency_ms=sql_latency,
                    )

                    if sql_result.success and not sql_result.data.empty:
                        st.dataframe(sql_result.data, use_container_width=True)
                        df_save = sql_result.data

                        analyse = (f"{FINAL_ANSWER_PROMPT}\n"
                                   f"Question : {clean_question}\n"
                                   f"Données :\n{sql_result.data.to_string(index=False)}")
                        try:
                            response = llm_call_with_retry(analyse)
                        except Exception:
                            cols     = sql_result.data.columns.tolist()
                            nb       = len(sql_result.data)
                            response = (f"📊 {nb} résultat(s) trouvé(s). "
                                        f"Colonnes : {', '.join(cols)}. "
                                        f"Voir le tableau ci-dessus.")
                        st.markdown(response)

                        if veut_graphique and len(sql_result.data) >= 2:
                            chart_buf = generer_graphique(sql_result.data, clean_question)
                            if chart_buf:
                                st.image(chart_buf, use_container_width=True)
                                chart_save = chart_buf.getvalue()
                            else:
                                st.info("💡 Matplotlib non disponible.")
                        elif veut_graphique and len(sql_result.data) < 2:
                            st.info("ℹ️ Graphique non pertinent pour un résultat unique.")

                        status.update(label="✅ Terminé", state="complete")

                    else:
                        response = "Aucun résultat trouvé pour cette recherche."
                        st.info(response)
                        status.update(label="✅ Terminé", state="complete")

                else:
                    response = "⚠️ Requête SQL interdite."
                    st.error(response)
                    status.update(label="🛡️ Bloqué", state="error")

            except Exception as e:
                response = f"Erreur : {e}"
                st.error(response)
                status.update(label="❌ Erreur", state="error")

            finally:
                router.finalize_trace(
                    trace_id=trace_id,
                    response=response,
                    intent="SQL",
                    total_latency_ms=int((time.time() - t_global_start) * 1000),
                )

    if response:
        st.session_state.messages.append({
            "role":    "assistant",
            "content": response,
            "data":    df_save,
            "chart":   chart_save,
        })