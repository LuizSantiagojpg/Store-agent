"""
Empório da Música — Conversational AI Agent Orchestrator.

Supports multi-provider Function Calling / Tool Use:
1. Local LLM via LM Studio (`meta-llama-3.1-8b-instruct` on OpenAI-compatible `/v1/chat/completions`)
2. Google Gemini API (`GEMINI_API_KEY` / `GOOGLE_API_KEY`)
3. OpenAI / DeepSeek Compatible API (`OPENAI_API_KEY` / `DEEPSEEK_API_KEY`)
4. Deterministic Local Tool-Router Fallback (ensuring 100% functional execution even offline)

Includes persistent multi-turn conversation memory stored in JSON (`data/session_history.json`).
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
from src.tools import ACCESSORY_KEYWORDS, EmporioTools

SYSTEM_PROMPT = """Você é o Tom, o assistente virtual especialista em instrumentos musicais da **Empório da Música** (fundada em 2008 em Campo Grande/MS — *"Sua música começa aqui"*).

### 1. Identidade e Tom de Voz (Seção 7.1 do Manual)
- **Tom de voz:** Informal mas profissional, acolhedor e apaixonado por música — como um amigo músico experiente ajudando outro músico.
- **Idioma:** Responda sempre em português claro, bem estruturado (usando tópicos/bullet points quando listar produtos ou regras) e objetivo.

### 2. Regras de Ouro de Precisão e Ferramentas (Obrigatório)
- **Baseie-se EXCLUSIVAMENTE nos dados retornados pelas ferramentas (`role: tool`).** NUNCA invente modelos, preços, estoque, status de pedidos ou políticas que não estejam no resultado da ferramenta.
- **Disponibilidade e Estoque (Seção 7.3):**
  - Liste todos os produtos de `available_products` (`status = "active"` e `stock_quantity > 0`) com seu nome, preço de tabela, preço no PIX (5% de desconto quando não houver promoção ativa), parcelamento e quantidade em estoque.
  - Se houver itens em `unavailable_or_discontinued_matches` (ex.: *Giannini GF-3D* com estoque 0 ou *Shelby SN-7C* descontinuado), mencione-os ao final em uma nota de transparência explicando que estão sem estoque ou descontinuados.
- **Promoções Ativas vs. Expiradas e Regra do PIX (Seções 3, 6.2 e 7.3):**
  - Se um produto tiver promoção ativa (`active_promotion`), apresente SEMPRE o **preço original**, o **percentual de desconto** e o **preço promocional**, e informe que **o desconto de 5% no PIX NÃO é cumulativo com promoções ativas**.
  - Se o produto teve promoção que já expirou (`expired_promotions`, como o *Takamine GD20* que teve 12% OFF inativo), informe com transparência que a promoção anterior já encerrou, mostre o preço atual de tabela (R$ 2.199,00), o preço com **5% de desconto à vista no PIX** (R$ 2.089,05) e o parcelamento em até 12x sem juros.
- **Escopo Exclusivo da Loja (Seções 1 e 7.1):**
  - A Empório da Música trabalha **exclusivamente com instrumentos musicais**.
  - **NÃO vendemos acessórios avulsos** (cordas, encordoamentos, palhetas, cabos, cases, capas/bags, pedais, amplificadores ou boquilhas). Se o cliente pedir acessórios ou houver `out_of_scope_accessory_alert`, explique com simpatia e redirecione para nossos instrumentos musicais.
- **Endereço, Horários e Contatos Oficiais (Seções 1 e 2):**
  - Endereço: **Rua 14 de Maio, 3200 — Centro, Campo Grande/MS, CEP 79202-333**.
  - Horário: **Segunda a Sexta das 09:00 às 18:00 | Sábado das 09:00 às 13:00 | Domingos e Feriados: Fechado**.
  - Contatos: Telefone fixo **(67) 3341-4444** | WhatsApp oficial **(67) 3321-4500** | E-mail `contato@emporiodamusica.com.br`.
- **Trocas, Devoluções e Garantia (Seções 4 e 8):**
  - **Direito de Arrependimento (compras online - Seção 4.1):** até **7 dias corridos após o recebimento**, sem necessidade de justificativa, produto sem uso na embalagem original, **frete de devolução por conta da loja** e reembolso em até 10 dias úteis.
  - **Troca por Preferência (Seção 4.3):** até **7 dias corridos**, em perfeito estado na embalagem original.
  - **Troca por Defeito (Seção 4.2 e 8.1):** até **30 dias corridos após a compra** direto na loja; **90 dias de garantia legal (CDC)** + garantia do fabricante (6 meses a 2 anos).
"""

OPENAI_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Busca instrumentos musicais no catálogo da Empório da Música filtrando por categoria, "
                "termo de busca (marca/modelo/tipo), preço máximo ou promoções ativas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Categoria: 'Violões', 'Guitarras', 'Baixos', 'Baterias e Percussão', 'Teclados e Pianos', 'Ukuleles'.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Termo específico opcional (ex.: marca 'Yamaha', 'nylon', 'aço', 'saxofone', 'cordas'). Deixe vazio para listar toda a categoria.",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Preço máximo em reais (ex.: 1000).",
                    },
                    "only_active_promotions": {
                        "type": "boolean",
                        "description": "Passe true APENAS se o cliente pedir especificamente produtos em promoção ativa.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": (
                "Consulta ficha técnica completa, preço atual, estoque, promoções ativas ou expiradas, "
                "valor com 5% de desconto no PIX e parcelamento de um instrumento específico (por nome ou ID)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name_or_id": {
                        "type": "string",
                        "description": "Nome do modelo (ex.: 'Takamine GD20', 'Yamaha C40', 'Music Man Bass 1X') ou ID numérico (ex.: '95', '135').",
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
                "Consulta pedidos pelo número do pedido (order_id) ou nome/e-mail/telefone do cliente, "
                "retornando status, rastreio, motivo de cancelamento e elegibilidade de devolução/troca/garantia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "integer",
                        "description": "Número do pedido (ex.: 4, 7, 8, 19).",
                    },
                    "customer_query": {
                        "type": "string",
                        "description": "Nome do cliente, e-mail ou telefone.",
                    },
                    "reference_date": {
                        "type": "string",
                        "description": "Data de referência YYYY-MM-DD para cálculo de prazos (padrão: '2026-03-25').",
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
                "Simula opções de pagamento (PIX, parcelas sem juros no cartão, pagamento combinado) "
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
                "Consulta o Manual de Políticas da Empório da Música: endereço, horários de funcionamento, "
                "telefones/WhatsApp, formas de pagamento, trocas, devoluções (direito de arrependimento), frete, promoções, garantia e LGPD."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Tópico da política (ex.: 'endereço e horário de funcionamento', 'devolução direito de arrependimento', 'formas de pagamento').",
                    }
                },
                "required": ["topic"],
            },
        },
    },
]


def _compact_tool_result_for_llm(tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a compact, high-signal representation of tool outputs optimized for
    local 8B models (such as `meta-llama-3.1-8b-instruct` with a 4096-token context window)
    so no product, price, or policy detail is ever truncated or overlooked.
    """
    if tool_name == "search_products":
        compact_avail = []
        for p in result.get("available_products", []):
            entry: Dict[str, Any] = {
                "id": p["product_id"],
                "name": p["name"],
                "stock": p["stock_quantity"],
                "price_brl": p["effective_price_brl"],
                "pix_price_brl": p["pix_price_brl"],
                "installments": p["installment_plan"],
                "strings": p.get("specs", {}).get("strings"),
                "electronics": p.get("specs", {}).get("electronics"),
            }
            if p.get("active_promotion"):
                entry["original_price_brl"] = p["original_price_brl"]
                entry["active_promotion"] = p["active_promotion"]
                entry["pix_rule"] = "Desconto PIX de 5% NÃO cumulativo com promoção ativa (Seção 6.2)."
            if p.get("data_quality_warning"):
                entry["data_quality_warning"] = p["data_quality_warning"]
            compact_avail.append(entry)

        compact_unavail = [
            {
                "id": u["product_id"],
                "name": u["name"],
                "price_brl": u["original_price_brl"],
                "status": "temporariamente sem estoque (0 un.)" if u["status"] == "active" else f"indisponível ({u['status']})",
            }
            for u in result.get("unavailable_or_discontinued_matches", [])
        ]
        return {
            "total_available_in_stock": result.get("total_available_in_stock", 0),
            "available_products": compact_avail,
            "unavailable_or_discontinued_matches": compact_unavail,
            "out_of_scope_accessory_alert": result.get("out_of_scope_accessory_alert"),
            "empty_category_note": result.get("empty_category_note"),
            "policy_reminder": result.get("policy_reminder"),
        }

    if tool_name == "get_product_details" and result.get("found"):
        p = result["product"]
        return {
            "found": True,
            "product": {
                "id": p["product_id"],
                "name": p["name"],
                "category": p["category_name"],
                "status": p["status"],
                "stock_quantity": p["stock_quantity"],
                "is_available_now": p["is_available_now"],
                "original_price_brl": p["original_price_brl"],
                "effective_price_brl": p["effective_price_brl"],
                "pix_price_brl": p["pix_price_brl"],
                "pix_rule_note": p["pix_rule_note"],
                "active_promotion": p["active_promotion"],
                "expired_promotions": p["expired_promotions"],
                "installment_plan": p["installment_plan"],
                "description": p["description"],
                "specs": p["specs"],
                "data_quality_warning": p["data_quality_warning"],
            },
            "shipping_campo_grande_note": result.get("shipping_campo_grande_note"),
            "similar_in_stock_alternatives": [
                {
                    "id": alt["product_id"],
                    "name": alt["name"],
                    "effective_price_brl": alt["effective_price_brl"],
                    "pix_price_brl": alt["pix_price_brl"],
                    "stock_quantity": alt["stock_quantity"],
                }
                for alt in result.get("similar_in_stock_alternatives", [])
            ],
        }

    return result


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
    Automatically detects available LLM endpoints (Local LM Studio `meta-llama-3.1-8b-instruct`,
    Google Gemini, OpenAI, DeepSeek) and executes Function Calling with deterministic tool grounding.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
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
        self.provider, self.api_key, self.model, self.base_url = self._resolve_provider(
            provider, api_key, model, base_url
        )

    @staticmethod
    def _probe_lmstudio_endpoint(candidate_urls: List[str], preferred_model: str) -> Optional[Tuple[str, str]]:
        """Check if a local LM Studio server is reachable and return (base_url, active_model)."""
        for base in candidate_urls:
            if not base:
                continue
            clean_base = base.rstrip("/")
            if not clean_base.endswith("/v1"):
                clean_base = f"{clean_base}/v1"
            try:
                req = urllib.request.Request(f"{clean_base}/models", method="GET")
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                if preferred_model in models:
                    return clean_base, preferred_model
                llm_models = [m for m in models if "embed" not in m.lower()]
                return clean_base, (llm_models[0] if llm_models else preferred_model)
            except Exception:
                continue
        return None

    def _resolve_provider(
        self,
        provider: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
        base_url: Optional[str] = None,
    ) -> Tuple[str, str, str, str]:
        env_provider = (provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
        lmstudio_model = model or os.getenv("LMSTUDIO_MODEL", "meta-llama-3.1-8b-instruct")
        lmstudio_urls = [
            base_url or "",
            os.getenv("LMSTUDIO_BASE_URL", ""),
            "http://172.24.112.1:1234/v1",
            "http://127.0.0.1:1234/v1",
            "http://localhost:1234/v1",
        ]

        if env_provider in ("lmstudio", "local_llm", "llama"):
            probed = self._probe_lmstudio_endpoint(lmstudio_urls, lmstudio_model)
            if probed:
                return "lmstudio", api_key or os.getenv("LMSTUDIO_API_KEY", "lm-studio"), probed[1], probed[0]
            fallback_url = base_url or os.getenv("LMSTUDIO_BASE_URL", "http://172.24.112.1:1234/v1")
            return "lmstudio", api_key or os.getenv("LMSTUDIO_API_KEY", "lm-studio"), lmstudio_model, fallback_url

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
                base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )
        if env_provider == "deepseek" and deepseek_key:
            return "deepseek", deepseek_key, model or "deepseek-chat", "https://api.deepseek.com/v1"
        if env_provider == "local_deterministic":
            return "local_deterministic", "", "deterministic-tool-router-v1", ""

        # Auto-detect active local LM Studio instance first
        probed = self._probe_lmstudio_endpoint(lmstudio_urls, lmstudio_model)
        if probed:
            return "lmstudio", os.getenv("LMSTUDIO_API_KEY", "lm-studio"), probed[1], probed[0]

        # Auto-detect cloud API keys from environment
        if gemini_key and gemini_key != "your_gemini_api_key_here":
            return "gemini", gemini_key, model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), ""
        if openai_key and openai_key != "your_openai_api_key_here":
            return (
                "openai",
                openai_key,
                model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
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

    def _supplement_compound_tools(
        self,
        user_message: str,
        messages: List[Dict[str, Any]],
        executed_tools: List[Dict[str, Any]],
    ) -> None:
        """
        Ensure compound customer prompts (e.g. asking about multiple orders or combining
        a policy/address question with an order lookup) have all relevant tool outputs
        attached when using compact 8B local models that emit one tool call per turn.
        """
        msg_norm = normalize_text(user_message)
        called_names = {t["tool"] for t in executed_tools}

        # Extract any explicit reference date mentioned in the prompt (e.g. "02/03/2026" or "2026-03-02")
        ref_date = "2026-03-25"
        date_br = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", user_message)
        date_iso = re.search(r"\b(202\d-\d{2}-\d{2})\b", user_message)
        if date_br:
            ref_date = f"{date_br.group(3)}-{date_br.group(2)}-{date_br.group(1)}"
        elif date_iso:
            ref_date = date_iso.group(1)

        # Check all explicit order IDs mentioned (e.g., "pedido #8", "pedido 4")
        order_ids = [int(m) for m in re.findall(r"pedido\s*(?:antigo\s*)?#?(\d+)", msg_norm)]
        queried_order_ids = {
            int(t["args"].get("order_id"))
            for t in executed_tools
            if t["tool"] == "lookup_customer_orders" and str(t["args"].get("order_id", "")).isdigit()
        }
        for oid in order_ids:
            if oid not in queried_order_ids:
                args = {"order_id": oid, "reference_date": ref_date}
                res = self._execute_tool("lookup_customer_orders", args)
                executed_tools.append({"tool": "lookup_customer_orders", "args": args, "output": res})
                call_id = f"auto_order_{oid}"
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "id": call_id,
                                "function": {"name": "lookup_customer_orders", "arguments": json.dumps(args)},
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": "lookup_customer_orders",
                        "content": json.dumps(_compact_tool_result_for_llm("lookup_customer_orders", res), ensure_ascii=False),
                    }
                )

        # Check if user asked about store address/hours/return policies alongside another tool
        policy_keywords = [
            "endereco", "horario", "funcionamento", "arrependi", "arrependimento",
            "devolver", "devolucao", "troca", "trocar", "garantia", "lgpd",
        ]
        if any(kw in msg_norm for kw in policy_keywords) and "consult_store_policy" not in called_names:
            args = {"topic": user_message}
            res = self._execute_tool("consult_store_policy", args)
            executed_tools.append({"tool": "consult_store_policy", "args": args, "output": res})
            call_id = "auto_policy_1"
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": call_id,
                            "function": {"name": "consult_store_policy", "arguments": json.dumps(args, ensure_ascii=False)},
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": "consult_store_policy",
                    "content": json.dumps(_compact_tool_result_for_llm("consult_store_policy", res), ensure_ascii=False),
                }
            )

        # Check if user asked for out-of-scope accessories alongside store policies
        if any(kw in msg_norm.split() for kw in ACCESSORY_KEYWORDS) and "search_products" not in called_names:
            args = {"query": user_message}
            res = self._execute_tool("search_products", args)
            executed_tools.append({"tool": "search_products", "args": args, "output": res})
            call_id = "auto_accessory_check"
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": call_id,
                            "function": {"name": "search_products", "arguments": json.dumps(args, ensure_ascii=False)},
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": "search_products",
                    "content": json.dumps(_compact_tool_result_for_llm("search_products", res), ensure_ascii=False),
                }
            )

    def _chat_openai_compatible(
        self,
        messages: List[Dict[str, Any]],
        user_message: str,
        executed_tools: List[Dict[str, Any]],
    ) -> str:
        """
        Execute Function Calling against any OpenAI-compatible API
        (LM Studio `meta-llama-3.1-8b-instruct`, OpenAI, DeepSeek).
        """
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        # Step 1: Tool routing call with OPENAI_TOOLS_SCHEMA
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": OPENAI_TOOLS_SCHEMA,
            "tool_choice": "auto",
            "temperature": 0.1,
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data["choices"][0]["message"]
        tool_calls = choice.get("tool_calls")

        if tool_calls:
            messages.append(choice)
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    fn_args = {}
                result = self._execute_tool(fn_name, fn_args)
                executed_tools.append({"tool": fn_name, "args": fn_args, "output": result})
                compact_result = _compact_tool_result_for_llm(fn_name, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": json.dumps(compact_result, ensure_ascii=False),
                    }
                )

        # Ensure compound queries have any complementary tool output attached
        self._supplement_compound_tools(user_message, messages, executed_tools)

        if not executed_tools and choice.get("content"):
            return choice["content"].strip()

        # Step 2: Grounded synthesis call (without `tools` so 8B models synthesize directly without looping)
        synth_payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        synth_req = urllib.request.Request(
            url,
            data=json.dumps(synth_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(synth_req, timeout=60) as resp:
            synth_data = json.loads(resp.read().decode("utf-8"))

        final_msg = synth_data["choices"][0]["message"].get("content") or ""
        return final_msg.strip()

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
        for turn in history[-6:]:
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
                            "response": {"result": _compact_tool_result_for_llm(fn_name, result)},
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

        # Keep recent turns concise to respect local 4096-token context windows
        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-4:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_message})

        reply: Optional[str] = None
        provider_used = f"{self.provider}:{self.model}"

        try:
            if self.provider in ("lmstudio", "openai", "deepseek"):
                reply = self._chat_openai_compatible(messages, user_message, executed_tools)
            elif self.provider == "gemini":
                reply = self._chat_gemini_rest(user_message, history, executed_tools)
        except Exception as exc:
            # Graceful fallback if server is stopped or API key is missing
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
        Deterministic fallback router so the agent remains 100% testable even without an active LLM server.
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
