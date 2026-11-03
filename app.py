"""
Streamlit Web UI for the Empório da Música Customer Service AI Agent.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from src.agent import EmporioAgent

st.set_page_config(
    page_title="Empório da Música — AI Agent",
    page_icon="🎸",
    layout="wide",
)

if "agent" not in st.session_state:
    st.session_state.agent = EmporioAgent()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = "streamlit_user"

agent: EmporioAgent = st.session_state.agent

with st.sidebar:
    st.title("🎸 Empório da Música")
    st.caption("Sua música começa aqui — Campo Grande/MS")
    st.markdown(f"**Motor Ativo:** `{agent.provider} ({agent.model})`")

    st.divider()
    st.subheader("⚡ Cenários Rápidos de Teste")
    sample_prompts = [
        "Quais opções de violões disponíveis custando até R$1000?",
        "Quanto custa o Takamine GD20? Ele ainda está na promoção?",
        "Qual o endereço e horário de funcionamento da loja? Vocês vendem encordoamento e pedal?",
        "Sou a Letícia Rocha (pedido #7) e também queria saber do pedido #8 da Ana Carolina. Me arrependi da compra, posso devolver?",
        "Quais instrumentos estão com promoção ativa hoje na loja e como funciona o desconto no PIX?",
    ]
    for prompt in sample_prompts:
        if st.button(prompt, use_container_width=True):
            st.session_state.pending_prompt = prompt

    st.divider()
    if st.button("🧹 Limpar Conversa", use_container_width=True):
        agent.memory.clear(st.session_state.session_id)
        st.session_state.messages = []
        st.rerun()

st.title("🎸 Atendimento Inteligente — Empório da Música")
st.markdown(
    "Assistente virtual integrado em tempo real ao catálogo SQLite (`products`, `promotions`, `orders`, `customers`) "
    "e ao Manual de Políticas e Procedimentos (`políticas_da_loja.pdf`)."
)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("tool_calls"):
            with st.expander(f"🔧 Inspecionar {len(msg['tool_calls'])} Tool Call(s) executadas"):
                for tc in msg["tool_calls"]:
                    st.markdown(f"**Tool:** `{tc['tool']}`")
                    st.json({"arguments": tc["args"], "result": tc["output"]})

user_prompt = st.chat_input("Digite sua mensagem para a Empório da Música...")
if "pending_prompt" in st.session_state and st.session_state.pending_prompt:
    user_prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

if user_prompt:
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Consultando catálogo e políticas da Empório da Música..."):
            res = agent.chat(user_prompt, session_id=st.session_state.session_id)
        st.markdown(res["reply"])
        if res["tool_calls"]:
            with st.expander(f"🔧 Inspecionar {len(res['tool_calls'])} Tool Call(s) executadas"):
                for tc in res["tool_calls"]:
                    st.markdown(f"**Tool:** `{tc['tool']}`")
                    st.json({"arguments": tc["args"], "result": tc["output"]})

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": res["reply"],
            "tool_calls": res["tool_calls"],
        }
    )
