import os
import re
from urllib.parse import urlparse
import html

import streamlit as st
import streamlit.components.v1 as components

# Google Sheets logging
import gspread
from google.oauth2 import service_account
from datetime import datetime
from zoneinfo import ZoneInfo


# =========================
# Config base
# =========================
LOGO_URL = "https://mocainteractive.com/wp-content/uploads/2025/04/cropped-moca_logo-positivo-1.png"
FAVICON_URL = "https://mocainteractive.com/wp-content/uploads/2025/04/cropped-moca-instagram-icona-1.png"

# Modello: nascosto nel frontend, sovrascrivibile da Secrets
MODEL_DEFAULT = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")


# =========================
# Helper
# =========================
def clean_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.replace("www.", "") if netloc else ""
    except Exception:
        return ""


def char_count(text: str) -> int:
    return len(text)


def enforce_length(text: str, min_c: int, max_c: int) -> str:
    """Se supera max, taglia “morbido” alla fine di una frase; se è sotto min, lascia invariato."""
    if len(text) <= max_c:
        return text
    trimmed = text[:max_c]
    m = re.search(r"(.+[\.!?])[^\.!?]*$", trimmed, re.S)
    return m.group(1) if m else trimmed


def log_to_sheet(keyword: str, url: str, ctype: str, language: str, chars: int, model: str):
    """
    Scrive una riga sullo Sheet configurato in Secrets.
    Colonne: N | Data | Ora | Keyword | URL | Tipo | Lingua | Caratteri | Modello
    """
    try:
        sheet_id = st.secrets["LOG_SHEET_ID"]
        sheet_name = st.secrets.get("LOG_SHEET_NAME", "logs")
        tzname = st.secrets.get("TIMEZONE", "Europe/Rome")
        sa_info = st.secrets.get("gcp_service_account")
        if not sa_info:
            return  # non bloccare l'app se manca la configurazione

        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(sheet_name)

        now = datetime.now(ZoneInfo(tzname))
        d = now.strftime("%Y-%m-%d")
        t = now.strftime("%H:%M:%S")

        n = len(ws.get_all_values())  # progressivo (header compreso)
        row = [n, d, t, keyword or "", url or "", ctype or "", language or "", int(chars), model or ""]
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.info(f"ℹ️ Log non registrato: {e}")


# =========================
# LLM client (OpenAI)
# =========================
def get_openai_client():
    key = st.secrets.get("OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    if not key:
        st.error("⚠️ Inserisci una API key valida (Secrets: OPENAI_API_KEY).")
        return None
    try:
        from openai import OpenAI  # type: ignore
        return OpenAI(api_key=key)
    except Exception as e:
        st.error(f"Errore di import/inizializzazione OpenAI: {e}")
        return None


def call_openai(client, model: str, system_prompt: str, user_prompt: str,
                temperature: float = 0.5, max_tokens: int = 1000) -> str:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        st.error(f"Errore chiamando il modello: {e}")
        return ""


# =========================
# UI
# =========================
st.set_page_config(page_title="SEO Writer", page_icon=FAVICON_URL, layout="wide")

st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:12px;margin-top:-8px;">
      <img src="{LOGO_URL}" alt="Moca Interactive" style="height:40px;">
      <h1 style="margin:0;font-weight:700;">SEO Writer</h1>
    </div>
    """,
    unsafe_allow_html=True,
)

st.caption("Genera testi SEO per Smeg.com a partire da keyword, URL e indicazioni. Pensato per pagine di listing/categoria o di prodotto.")

with st.sidebar:
    st.header("⚙️ Modello & API")
    provider = st.selectbox("Provider", ["OpenAI"], index=0, help="Attualmente supportato: OpenAI")
    temperature = st.slider("Temperature", 0.0, 1.2, 0.4, 0.1, help="Più alto = più creativo")

    st.header("✍️ Stile")
    enable_en = bool(st.secrets.get("ENABLE_ENGLISH", False))
    lang_options = ["Italiano"] + (["English (🔒 Pro)"] if not enable_en else ["English"])
    lang_choice = st.selectbox("Lingua", lang_options, index=0)
    language = "English" if ("English" in lang_choice and enable_en) else "Italiano"
    if ("English" in lang_choice and not enable_en):
        st.info("Per sbloccare l'inglese contatta Moca per il pacchetto avanzato.")

    tone = st.selectbox("Tono", ["professionale", "conversazionale", "autorevole", "persuasivo", "neutro"], index=0)
    brand_voice = st.text_area("Voce del brand (opzionale)")

    st.header("🔎 SEO")
    col_len1, col_len2 = st.columns(2)
    with col_len1:
        target_min = st.number_input("Min caratteri", min_value=100, max_value=5000, value=500, step=50)
    with col_len2:
        target_max = st.number_input("Max caratteri", min_value=100, max_value=5000, value=600, step=50)
    if target_min > target_max:
        st.warning("⚠️ Il minimo non può superare il massimo.")
    target_chars = int((target_min + target_max) / 2)

st.subheader("Dati di input")
col1, col2 = st.columns(2)
with col1:
    keyword = st.text_input("Keyword principale", placeholder="es. frigoriferi da incasso")
    url = st.text_input("URL di riferimento (per contesto e internal linking)")
    content_type = st.selectbox("Tipo contenuto", ["Listing", "Scheda prodotto"], index=0)
with col2:
    intro_text = st.text_area("Testo introduttivo (opzionale)")
    bullets = st.text_area("Bullet list (una per riga – per scheda prodotto)")
    extra_guidelines = st.text_area("Linee guida aggiuntive (regole SEO, CTA, termini da usare/evitare)")

start = st.button("🚀 Genera testo SEO")


# =========================
# Prompt
# =========================
SYSTEM_PROMPT_BASE = """
Sei un SEO copywriter esperto di e-commerce. Genera testi introduttivi per pagine categoria (listing) o schede prodotto.

Regole fisse:
- Rispetta la lingua richiesta.
- Mantieni tra {min_c} e {max_c} caratteri spazi inclusi (target {target_chars}). È TASSATIVO restare nel range richiesto.
- Evita keyword stuffing; usa sinonimi e varianti semantiche pertinenti al search intent.
- Tono: professionale, chiaro, allineato al brand.
- NON usare H1/H2/H3, elenchi, markdown, emoji o caratteri speciali (ok “-” o “|” se utili).
- Non è un blog: dev’essere breve e funzionale alla pagina {ctype}.
- Non inserire meta, FAQ, link esterni o spiegazioni.
- Rispondi solo con il testo finale.
""".strip()

USER_PROMPT_TEMPLATE = """
CONTESTO:
- Keyword principale: "{keyword}"
- URL del sito: {url} (dominio: {domain})
- Tipo contenuto: {ctype}
- Tono: {tone}
- Voce del brand: {brand_voice}
- Linee guida extra: {extra_guidelines}
- Lingua: {language}

MATERIALI:
- Intro (facoltativa):
{intro_text}
- Bullet list (solo se scheda prodotto):
{bullets}

ISTRUZIONI:
1) Scrivi un testo introduttivo tra {min_c} e {max_c} caratteri spazi inclusi (target {target_chars}).
2) Inserisci in modo naturale almeno una delle keyword o varianti correlate all’intento di ricerca.
3) Descrivi chiaramente tipologia di prodotti e valore/stile del brand.
4) Evita ripetizioni e punteggiatura superflua; niente titoli/elenco/meta/FAQ/link esterni.
""".strip()


# =========================
# Run
# =========================
if start:
    if not keyword.strip():
        st.warning("Inserisci almeno la keyword principale.")
        st.stop()

    domain = clean_domain(url)
    system_prompt = SYSTEM_PROMPT_BASE.format(
        min_c=target_min, max_c=target_max, target_chars=target_chars, ctype=content_type
    )
    user_prompt = USER_PROMPT_TEMPLATE.format(
        keyword=keyword,
        url=url or "(non fornito)",
        domain=domain or "(non disponibile)",
        ctype=content_type,
        tone=tone,
        brand_voice=brand_voice or "(non specificata)",
        extra_guidelines=extra_guidelines or "(nessuna)",
        language=language,
        intro_text=intro_text or "",
        bullets=bullets or "",
        min_c=target_min,
        max_c=target_max,
        target_chars=target_chars,
    )

    if provider == "OpenAI":
        client = get_openai_client()
        if client is None:
            st.stop()

        # regola output esplicita
        system_prompt += "\n\nOUTPUT:"
        output_rules = (
            "Restituisci esclusivamente il testo introduttivo (un unico blocco), "
            "senza titoli, sottotitoli, elenchi, meta, FAQ, link esterni o commenti."
        )
        user_prompt = user_prompt + "\n\n" + output_rules

        with st.spinner("Generazione in corso..."):
            content = call_openai(
                client, MODEL_DEFAULT, system_prompt, user_prompt,
                temperature=temperature, max_tokens=1000
            )

        if not content:
            st.stop()

        # Primo conteggio e micro-fix se fuori range
        cc = char_count(content)
        if cc < target_min or cc > target_max:
            fix_prompt = (
                f"Riscrivi mantenendo il senso ma rientrando tra {target_min}-{target_max} caratteri "
                f"(spazi inclusi, target {target_chars}). Restituisci solo il contenuto, nessun commento."
            )
            content = call_openai(
                client, MODEL_DEFAULT, system_prompt, content + "\n\n" + fix_prompt,
                temperature=temperature, max_tokens=1000
            )
            cc = char_count(content)

        # Normalizza e ricalcola DOPO il trimming
        content = enforce_length((content or "").strip(), target_min, target_max)
        cc = char_count(content)

        # Log su Google Sheet (non bloccare l'app se fallisce)
        try:
            log_to_sheet(
                keyword=keyword,
                url=url,
                ctype=content_type,
                language=language,
                chars=cc,
                model=MODEL_DEFAULT,
            )
        except Exception as e:
            st.info(f"ℹ️ Log non registrato: {e}")

        # Messaggio con conteggio esatto
        if cc < target_min or cc > target_max:
            st.warning(f"⚠️ Caratteri: {cc} (target {target_min}-{target_max}).")
        else:
            st.success(f"Fatto ✅ — {cc} caratteri (target {target_min}-{target_max}).")

        # Pulsante "Copia testo" compatto
        escaped = html.escape(content)
        components.html(f"""
<div>
  <button id="copyBtn" style="padding:8px 12px;border:1px solid #ddd;border-radius:8px;background:#fff;cursor:pointer">
    📋 Copia testo
  </button>
  <textarea id="toCopy" style="position:absolute;left:-9999px;top:-9999px">{escaped}</textarea>
</div>
<script>
  const btn = document.getElementById('copyBtn');
  btn.addEventListener('click', async () => {{
    const el = document.getElementById('toCopy');
    try {{
      await navigator.clipboard.writeText(el.value);
      btn.innerText = '✅ Copiato!';
    }} catch (e) {{
      el.select();
      document.execCommand('copy');
      btn.innerText = '✅ Copiato!';
    }}
    setTimeout(() => btn.innerText = '📋 Copia testo', 1500);
  }});
</script>
        """, height=70)

        st.divider()
        st.markdown(content)

    else:
        st.error("Provider non supportato al momento.")
