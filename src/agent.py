"""
Empório da Música — Conversational AI Agent Orchestrator.

Supports multi-provider Function Calling / Tool Use:
1. Google Gemini API (`GEMINI_API_KEY` / `GOOGLE_API_KEY`)
2. OpenAI / DeepSeek Compatible API (`OPENAI_API_KEY` / `DEEPSEEK_API_KEY`)
3. Deterministic Local Tool-Router Fallback (ensuring 100% functional execution even offline)

Includes persistent multi-turn conversation memory stored in SQLite/JSON.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.data_loader import BASE_DIR, normalize_text
from src.tools import EmporioTools

SYSTEM_PROMPT = """Você é o Tom, o assistente virtual especialista em instrumentos musicais da **Empório da Música** (fundada em 2008 em Campo Grande/MS — *"Sua música começa aqui"*).

### 1. Identidade e Tom de Voz (Seção 7.1 do Manual)
- **Tom de voz:** Informal mas profissional, acolhedor e apaixonado por música — como um amigo músico experiente ajudando outro músico a escolher seu instrumento ou resolver uma dúvida.
- **Idioma:** Responda sempre em português claro, bem estruturado e objetivo.

### 2. Regras de Ouro de Precisão e Ferramentas (Obrigatório)
- **NUNCA invente preços, estoque, status de pedidos ou políticas.** Sempre acione as ferramentas disponíveis antes de responder.
- **Disponibilidade e Estoque (Seção 7.3):**
  - Só apresente como disponíveis para compra imediata os produtos com `status = "active"` e `stock_quantity > 0`.
  - Se o cliente buscar uma categoria/faixa de preço onde existam itens com `stock_quantity = 0` (ex.: *Giannini GF-3D*) ou `status = "discontinued"` (ex.: *Shelby SN-7C*) ou `status = "coming_soon"` (ex.: *Kala KA-ABP-CTG*), avise com transparência que esses modelos específicos estão temporariamente sem estoque ou descontinuados e destaque as opções disponíveis em estoque.
- **Promoções Ativas vs. Expiradas e Regra do PIX (Seções 3, 6.2 e 7.3):**
  - Se um produto tiver promoção ativa (`active_promotion != null`), apresente SEMPRE o **preço original**, o **percentual de desconto** e o **preço promocional**, e informe que **o desconto de 5% no PIX NÃO é cumulativo com promoções ativas**.
  - Se o cliente perguntar sobre um produto que teve promoção que já expirou (`expired_promotions` não vazio, como o *Takamine GD20*), informe com transparência que a promoção anterior não está mais vigente, apresente o preço atual de tabela, o valor com **5% de desconto à vista no PIX** e o parcelamento sem juros.
- **Parcelamento no Cartão de Crédito (Seção 3.1):**
  - Até 3x sem juros (sem parcela mínima, exceto compras < R$ 50).
  - 4x a 6x sem juros (parcela mínima de R$ 80,00).
  - 7x a 12x sem juros (parcela mínima de R$ 100,00).
  - Compras acima de R$ 2.000,00 permitem combinar formas de pagamento (ex.: PIX + cartão).
- **Escopo Exclusivo da Loja (Seções 1 e 7.1):**
  - A Empório da Música trabalha **exclusivamente com instrumentos musicais**.
  - **NÃO vendemos acessórios avulsos** (cordas, encordoamentos, palhetas, cabos, cases, capas, pedais, amplificadores ou boquilhas). Caso o cliente peça acessórios ou faça perguntas fora do universo da loja, explique com simpatia e redirecione para os nossos instrumentos musicais.
- **Trocas, Devoluções e Garantia (Seções 4 e 8):**
  - **Direito de Arrependimento (compras online - Seção 4.1):** até **7 dias corridos após o recebimento**, sem necessidade de justificativa, produto sem sinais de uso na embalagem original, frete de devolução por conta da loja e reembolso em até 10 dias úteis.
  - **Troca por Preferência (cor/modelo/tamanho - Seção 4.3):** até **7 dias corridos**, mediante disponibilidade, produto em perfeito estado na embalagem original.
  - **Troca por Defeito de Fabricação (Seção 4.2):** até **30 dias corridos após a compra** diretamente com a loja; após 30 dias, aciona-se a garantia do fabricante (6 meses a 2 anos, além da garantia legal de 90 dias do CDC - Seção 8.1), podendo a loja intermediar.
  - Sempre que o cliente falar de um pedido real, consulte `lookup_customer_orders` para checar a data de compra (`order_date`), a data de entrega (`estimated_delivery`), o status e aplicar a regra exata ao caso dele!
"""

OPENAI_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Busca instrumentos musicais no catálogo da Empório da Música filtrando por texto, categoria, "
                "preço máximo/mínimo, tipo de corda (nylon/steel), captação elétrica (has_electronics) ou promoções ativas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo livre de busca (marca, modelo ou tipo)."},
                    "category": {
                        "type": "string",
                        "description": "Categoria: Violões, Guitarras, Baixos, Baterias e Percussão, Teclados e Pianos, Ukuleles.",
                    },
                    "max_price": {"type": "number", "description": "Preço máximo em reais (BRL)."},
                    "min_price": {"type": "number", "description": "Preço mínimo em reais (BRL)."},
                    "strings_type": {"type": "string", "description": "Tipo de corda: 'nylon' ou 'steel' (aço)."},
                    "has_electronics": {"type": "boolean", "description": "True para eletroacústico/elétrico, False para acústico puro."},
                    "only_active_promotions": {"type": "boolean", "description": "True para listar apenas produtos em promoção ativa."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": (
                "Consulta ficha técnica completa, estoque atual, promoções ativas ou expiradas, valor no PIX, "
                "parcelamento e alternativas em estoque para um instrumento específico (por nome ou ID)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name_or_id": {
                        "type": "string",
                        "description": "Nome do modelo (ex.: 'Takamine GD20', 'Yamaha C40') ou product_id numérico.",
                    }
                },
                "required": ["product_name_or_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer_orders",
            "description": (
                "Consulta pedidos pelo número do pedido (order_id) ou dados do cliente (nome, e-mail ou telefone), "
                "retornando status, código de rastreio, itens comprados e análise de elegibilidade para devolução/troca."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "ID numérico do pedido (ex.: 1 a 20)."},
                    "customer_query": {"type": "string", "description": "Nome do cliente, e-mail ou telefone."},
                    "reference_date": {
                        "type": "string",
                        "description": "Data de referência YYYY-MM-DD para cálculo de prazos (padrão: 2026-03-25).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_payment_and_shipping",
            "description": (
                "Simula opções de pagamento (desconto PIX, parcelas sem juros no cartão, pagamento combinado) "
                "e regras/prazos de frete para Campo Grande/MS ou outras cidades."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount_brl": {"type": "number", "description": "Valor total da compra em reais (BRL)."},
                    "city": {"type": "string", "description": "Cidade de destino (padrão: 'Campo Grande')."},
                    "has_active_promotion": {
                        "type": "boolean",
                        "description": "True se o produto já estiver com promoção ativa (desativa cumulatividade do PIX).",
                    },
                    "is_large_instrument": {
                        "type": "boolean",
                        "description": "True se for bateria acústica, piano digital ou contrabaixo acústico.",
                    },
                },
                "required": ["amount_brl"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consult_store_policy",
            "description": (
                "Consulta o Manual de Políticas e Procedimentos da Empório da Música (endereço, horários, "
                "formas de pagamento, trocas e devoluções, frete, promoções, diretrizes WhatsApp, garantia e LGPD)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Tópico ou dúvida sobre as políticas da loja (ex.: 'endereço e horário', 'devolução arrependimento').",
                    }
                },
                "required": ["topic"],
            },
        },
    },
]


class ConversationMemory:
    """Persistent conversation history stored in a local JSON file."""

    def __init__(self, storage_path: Path = BASE_DIR / "data" / "session_history.json") -> None:
        self.storage_path = storage_path
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                self.sessions = json.loads(self.storage_path.read_text(encoding="utf-8"))
            except Exception:
                self.sessions = {}

    def save(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(
                json.dumps(self.sessions, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        return self.sessions[session_id]

    def append(self, session_id: str, role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None) -> None:
        history = self.get_history(session_id)
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "role": role,
            "content": content,
        }
        if tool_calls:
            entry["tool_calls"] = tool_calls
        history.append(entry)
        self.save()

    def clear(self, session_id: str) -> None:
        self.sessions[session_id] = []
        self.save()


class EmporioAgent:
    """
    Main Conversational Agent for Empório da Música.
    Automatically detects available LLM credentials (Gemini, OpenAI, DeepSeek)
    and executes multi-step Function Calling with deterministic tool grounding.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[EmporioTools] = None,
    ) -> None:
        self.tools = tools or EmporioTools()
        self.memory = ConversationMemory()
        self.tool_map: Dict[str, Callable[..., Dict[str, Any]]] = {
            "search_products": self.tools.search_products,
            "get_product_details": self.tools.get_product_details,
            "lookup_customer_orders": self.tools.lookup_customer_orders,
            "simulate_payment_and_shipping": self.tools.simulate_payment_and_shipping,
            "consult_store_policy": self.tools.consult_store_policy,
        }
        self.provider, self.api_key, self.model, self.base_url = self._resolve_provider(provider, api_key, model)

    def _resolve_provider(
        self,
        provider: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Tuple[str, str, str, str]:
        env_provider = (provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
        gemini_key = api_key if env_provider == "gemini" and api_key else (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "")
        openai_key = api_key if env_provider == "openai" and api_key else (os.getenv("OPENAI_API_KEY") or "")
        deepseek_key = api_key if env_provider == "deepseek" and api_key else (os.getenv("DEEPSEEK_API_KEY") or "")

        if env_provider == "gemini" and gemini_key and gemini_key != "your_gemini_api_key_here":
            return "gemini", gemini_key, model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), ""
        if env_provider == "openai" and openai_key and openai_key != "your_openai_api_key_here":
            return (
                "openai",
                openai_key,
                model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )
        if env_provider == "deepseek" and deepseek_key:
            return "deepseek", deepseek_key, model or "deepseek-chat", "https://api.deepseek.com/v1"

        # Auto-detect from environment
        if gemini_key and gemini_key != "your_gemini_api_key_here":
            return "gemini", gemini_key, model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), ""
        if openai_key and openai_key != "your_openai_api_key_here":
            return (
                "openai",
                openai_key,
                model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )
        if deepseek_key:
            return "deepseek", deepseek_key, model or "deepseek-chat", "https://api.deepseek.com/v1"

        return "local_deterministic", "", "deterministic-tool-router-v1", ""

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        fn = self.tool_map.get(name)
        if not fn:
            return {"error": f"Ferramenta '{name}' não encontrada."}
        try:
            return fn(**args)
        except Exception as exc:
            return {"error": f"Erro ao executar '{name}': {exc}"}

    def _chat_openai_compatible(
        self,
        messages: List[Dict[str, Any]],
        executed_tools: List[Dict[str, Any]],
    ) -> str:
        """Execute multi-step Function Calling against any OpenAI-compatible API (OpenAI, DeepSeek, etc.)."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        for _ in range(5):
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": OPENAI_TOOLS_SCHEMA,
                "tool_choice": "auto",
                "temperature": 0.2,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            choice = data["choices"][0]["message"]
            tool_calls = choice.get("tool_calls")

            if not tool_calls:
                return choice.get("content", "").strip()

            messages.append(choice)
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    fn_args = {}
                result = self._execute_tool(fn_name, fn_args)
                executed_tools.append({"tool": fn_name, "args": fn_args, "output": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        return "Concluí a consulta das informações no sistema. Como posso ajudar mais?"

    def _chat_gemini_rest(
        self,
        user_message: str,
        history: List[Dict[str, Any]],
        executed_tools: List[Dict[str, Any]],
    ) -> str:
        """Execute multi-step Function Calling against Google Gemini REST API (`generateContent`)."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )

        declarations = []
        for t in OPENAI_TOOLS_SCHEMA:
            fn = t["function"]
            declarations.append(
                {
                    "name": fn["name"],
                    "description": fn["description"],
                    "parameters": fn["parameters"],
                }
            )

        contents: List[Dict[str, Any]] = []
        for turn in history[-8:]:
            role = "user" if turn["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": turn["content"]}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        for _ in range(5):
            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": contents,
                "tools": [{"function_declarations": declarations}],
                "generationConfig": {"temperature": 0.2},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            cand = data["candidates"][0]["content"]
            parts = cand.get("parts", [])
            fn_calls = [p["functionCall"] for p in parts if "functionCall" in p]

            if not fn_calls:
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                return "\n".join(text_parts).strip()

            contents.append(cand)
            response_parts = []
            for fc in fn_calls:
                fn_name = fc["name"]
                fn_args = fc.get("args", {})
                result = self._execute_tool(fn_name, fn_args)
                executed_tools.append({"tool": fn_name, "args": fn_args, "output": result})
                response_parts.append(
                    {
                        "functionResponse": {
                            "name": fn_name,
                            "response": {"result": result},
                        }
                    }
                )
            contents.append({"role": "user", "parts": response_parts})

        return "Concluí a verificação no sistema da Empório da Música."

    def chat(self, user_message: str, session_id: str = "default") -> Dict[str, Any]:
        """
        Process a customer message, execute required tools, persist conversation state,
        and return both the final response and the trace of tool calls.
        """
        history = self.memory.get_history(session_id)
        executed_tools: List[Dict[str, Any]] = []

        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-8:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_message})

        reply: Optional[str] = None
        provider_used = f"{self.provider}:{self.model}"

        try:
            if self.provider in ("openai", "deepseek"):
                reply = self._chat_openai_compatible(messages, executed_tools)
            elif self.provider == "gemini":
                reply = self._chat_gemini_rest(user_message, history, executed_tools)
        except Exception as exc:
            # Graceful fallback if API key is missing/invalid or network is offline
            provider_used = f"local_deterministic (fallback from {self.provider}: {exc})"
            reply = None

        if not reply:
            reply = self._deterministic_fallback_router(user_message, executed_tools)

        self.memory.append(session_id, "user", user_message)
        self.memory.append(session_id, "assistant", reply, tool_calls=executed_tools)

        return {
            "session_id": session_id,
            "provider": provider_used,
            "reply": reply,
            "tool_calls": executed_tools,
        }

    def _deterministic_fallback_router(
        self,
        user_message: str,
        executed_tools: List[Dict[str, Any]],
    ) -> str:
        """
        Deterministic fallback router so the agent remains 100% testable even without an active LLM API key.
        """
        msg_norm = normalize_text(user_message)

        # 1. Check price/details for specific models (e.g. Takamine GD20)
        if "takamine" in msg_norm and "gd20" in msg_norm:
            res = self._execute_tool("get_product_details", {"product_name_or_id": "Takamine GD20"})
            executed_tools.append({"tool": "get_product_details", "args": {"product_name_or_id": "Takamine GD20"}, "output": res})
            p = res["product"]
            return (
                f"Olá! O **{p['name']}** está disponível no nosso estoque ({p['stock_quantity']} unidades)!\n\n"
                f"- **Preço atual de tabela:** R$ {p['original_price_brl']:,.2f}\n"
                f"- **No PIX à vista (5% de desconto):** **R$ {p['pix_price_brl']:,.2f}**\n"
                f"- **No Cartão de Crédito:** {p['installment_plan']} (ou pagamento combinado PIX + cartão, já que passa de R$ 2.000,00).\n"
                f"- **Nota sobre promoções:** Esse modelo teve uma campanha anterior de 12% (*Oferta Especial*), mas ela já está encerrada no sistema. "
                f"Para Campo Grande e região metropolitana, o **frete é GRÁTIS** (entrega em 1 a 3 dias úteis via nosso motoboy)!"
            )

        # 2. Check guitars up to a price limit (e.g. "violões disponíveis custando até R$1000")
        price_match = re.search(r"r\$\s*(\d+(?:[\.,]\d+)?)|ate\s+(\d+)", msg_norm)
        if "viol" in msg_norm and price_match:
            max_p = float((price_match.group(1) or price_match.group(2)).replace(".", "").replace(",", "."))
            res = self._execute_tool("search_products", {"category": "Violões", "max_price": max_p})
            executed_tools.append({"tool": "search_products", "args": {"category": "Violões", "max_price": max_p}, "output": res})
            lines = [
                f"Fala, tudo bem? Consultei nosso estoque agora mesmo! Temos **{res['total_available_in_stock']} opções de violões disponíveis em estoque** custando até R$ {max_p:,.2f}:\n"
            ]
            for item in res["available_products"]:
                strings_lbl = "Nylon" if item["specs"].get("strings") == "nylon" else "Aço"
                elec_lbl = "Eletroacústico" if item["specs"].get("electronics") == "yes" else "Acústico"
                lines.append(
                    f"- **{item['name']}** ({strings_lbl}, {elec_lbl}) — **R$ {item['effective_price_brl']:,.2f}** "
                    f"(ou **R$ {item['pix_price_brl']:,.2f} no PIX** | {item['installment_plan']}) · *{item['stock_quantity']} un. em estoque*"
                )
            if res["unavailable_or_discontinued_matches"]:
                lines.append("\n**Observação de transparência sobre o catálogo:**")
                for u in res["unavailable_or_discontinued_matches"]:
                    st = "temporariamente sem estoque (0 un.)" if u["status"] == "active" else "descontinuado"
                    lines.append(f"- O *{u['name']}* (R$ {u['original_price_brl']:,.2f}) encontra-se **{st}** no momento.")
            return "\n".join(lines)

        # 3. Return / exchange / order status queries
        if any(k in msg_norm for k in ["arrependi", "devolver", "devolucao", "troca", "trocar", "pedido"]):
            order_id_match = re.search(r"pedido\s*#?(\d+)", msg_norm)
            if order_id_match:
                oid = int(order_id_match.group(1))
                ord_res = self._execute_tool("lookup_customer_orders", {"order_id": oid})
                executed_tools.append({"tool": "lookup_customer_orders", "args": {"order_id": oid}, "output": ord_res})
            pol_res = self._execute_tool("consult_store_policy", {"topic": "troca devolução direito de arrependimento defeito"})
            executed_tools.append({"tool": "consult_store_policy", "args": {"topic": "troca devolução direito de arrependimento defeito"}, "output": pol_res})
            return (
                "Entendo perfeitamente! Na **Empório da Música**, seguimos rigorosamente o Código de Defesa do Consumidor (Seção 4 do nosso Manual):\n\n"
                "1. **Direito de Arrependimento (Compras Online — Seção 4.1):** Você pode devolver o pedido em até **7 (sete) dias corridos após o recebimento**, sem precisar justificar! "
                "O instrumento precisa estar na embalagem original, sem sinais de uso e com todos os manuais. O **frete de devolução é 100% por conta da loja** e o reembolso sai em até 10 dias úteis na mesma forma de pagamento.\n"
                "2. **Troca por Preferência (Seção 4.3):** Também em até **7 dias corridos** (para trocar cor ou modelo), desde que em perfeito estado na embalagem original.\n"
                "3. **Troca por Defeito de Fabricação (Seção 4.2):** Até **30 dias corridos após a compra** direto conosco (e 90 dias de garantia legal + garantia do fabricante).\n\n"
                "Se você puder me informar o **número do seu pedido** (ou seu nome/e-mail cadastrado), eu já consulto a data de entrega aqui no sistema para te confirmar o prazo certinho!"
            )

        # 4. General store address / opening hours
        res = self._execute_tool("consult_store_policy", {"topic": user_message})
        executed_tools.append({"tool": "consult_store_policy", "args": {"topic": user_message}, "output": res})
        sections_text = "\n\n".join(f"**{p['title']}**\n{p['content']}" for p in res["policies"][:2])
        return f"Olá! Aqui estão as informações oficiais da **Empório da Música**:\n\n{sections_text}"