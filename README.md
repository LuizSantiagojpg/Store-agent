# 🎸 Empório da Música — Conversational AI Customer Service Agent

> **Artefact Technical Challenge — AI Engineer (Full-Stack for Generative AI Applications)**  
> **Author:** Luiz Roberto Santiago (`luizsanthyagorl@gmail.com`)  
> **Repository:** [https://github.com/LuizSantiagojpg/Store-agent](https://github.com/LuizSantiagojpg/Store-agent)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Local LLM](https://img.shields.io/badge/Local%20LLM-LM%20Studio%20%7C%20Llama--3.1--8B--Instruct-purple.svg)](#13-configuring-the-llm-provider-env)
[![Architecture](https://img.shields.io/badge/Architecture-Function%20Calling%20%2B%20SQLite%20%2B%20Policy%20RAG-success.svg)](#2-architecture--technical-decisions-justification)
[![Tests](https://img.shields.io/badge/Unit%20Tests-8%2F8%20Passing-brightgreen.svg)](#option-c--run-the-automated-test-suite)

This repository contains the end-to-end implementation of **Tom**, the virtual customer service agent for **Empório da Música** (a musical instruments store in Campo Grande/MS). The solution combines **deterministic Function Calling over normalized SQLite tables** (`products`, `categories`, `promotions`, `orders`, `order_items`, `customers`) with **section-grounded retrieval over the Store Policy Manual (`políticas_da_loja.pdf`)**, powered locally by **`meta-llama-3.1-8b-instruct` via LM Studio** (and compatible with Google Gemini, OpenAI, DeepSeek, or zero-key offline execution).

---

## 📑 Table of Contents
1. [Quick Start & Environment Setup](#-1-quick-start--environment-setup)
2. [Architecture & Technical Decisions Justification](#-2-architecture--technical-decisions-justification)
3. [Data Quality Audit & Hidden Edge Cases Handled](#-3-data-quality-audit--hidden-edge-cases-handled)
4. [Conversation Examples](#-4-conversation-examples)
5. [Known Limitations & What I Would Do With More Time](#-5-known-limitations--what-i-would-do-with-more-time)
6. [Use of AI Coding Assistants (Workflow Transparency)](#-6-use-of-ai-coding-assistants-workflow-transparency)

---

## 🚀 1. Quick Start & Environment Setup

### 1.1 Prerequisites
- **Python 3.10+** (Core agent, SQLite engine, OpenAI-compatible HTTP client, and test suite run using only Python's standard library — zero mandatory C-extensions!)
- **LM Studio (Recommended Local Provider):** Running `meta-llama-3.1-8b-instruct` on port `1234` (`http://172.24.112.1:1234/v1` or `http://127.0.0.1:1234/v1`).
- *(Optional)* `streamlit` for the interactive Web UI and `python-dotenv` for `.env` loading.

### 1.2 Installation
```bash
git clone https://github.com/LuizSantiagojpg/Store-agent.git
cd Store-agent

python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 1.3 Configuring the LLM Provider (`.env`)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
The orchestrator (`src/agent.py`) automatically detects your active provider in the following priority order:
- **1. Local LLM via LM Studio (Default):** Set `LLM_PROVIDER=lmstudio`, `LMSTUDIO_MODEL=meta-llama-3.1-8b-instruct`, and `LMSTUDIO_BASE_URL=http://172.24.112.1:1234/v1` (automatically probes `172.24.112.1:1234` and `127.0.0.1:1234`).
- **2. Google Gemini API:** Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...`
- **3. OpenAI / DeepSeek API:** Set `LLM_PROVIDER=openai` (or `deepseek`) and `OPENAI_API_KEY=...`
- **4. Zero-Key Offline Fallback (`local_deterministic`):** If no local LLM server is running and no cloud API key is configured, the agent transparently falls back to its built-in **Deterministic Local Tool-Router**, ensuring any evaluator can test all tools and scenarios immediately.

### 1.4 Running the Project

#### Option A — Interactive Terminal CLI
```bash
python cli.py
```
Or run a single-shot query displaying the exact tool calls triggered (use single quotes in PowerShell when passing `R$`):
```powershell
python cli.py -m 'Quais opções de violões disponíveis custando até R$1000?'
python cli.py -m 'Quanto custa o Takamine GD20? Vi um anúncio antigo de 12% de desconto nele, ainda está valendo?'
python cli.py -m 'Qual o endereço da loja e horário de funcionamento? Vocês vendem encordoamento e pedal?'
python cli.py -m 'Me arrependi da minha compra, posso devolver meu pedido #7?'
```

#### Option B — Interactive Streamlit Web UI (with Live Tool Call Inspector)
```bash
streamlit run app.py
```

#### Option C — Run the Automated Test Suite
```bash
python tests/test_agent_and_tools.py
# or:
python -m pytest tests/test_agent_and_tools.py -v
```

---

## 🏗️ 2. Architecture & Technical Decisions Justification

Following the challenge guideline (*"solve it in the simplest way possible"* while maximizing reliability), every technical choice was made to prevent LLM hallucinations on prices, stock, and business policies:

| Decision Area | Chosen Approach | Technical Justification |
| :--- | :--- | :--- |
| **Agent Framework / Approach** | **Hybrid Function Calling + Structured SQLite + Section-Indexed Policy RAG** (Native Python Orchestrator) | Pure RAG over CSV files fails at numerical filtering (e.g., `price <= 1000 AND stock > 0`), while pure Text-to-SQL risks SQL injection or missing implicit business rules (such as the non-cumulative PIX discount in Section 6.2). Exposing **5 deterministic domain tools** guarantees 100% mathematical accuracy on prices, installments, and dates while keeping the LLM focused on natural conversation and intent routing. Avoiding heavy abstractions keeps the codebase transparent, debuggable, and dependency-light. |
| **Model & Provider** | **Local `meta-llama-3.1-8b-instruct` via LM Studio (`/v1/chat/completions`) + Cloud & Offline Fallbacks** | Running `meta-llama-3.1-8b-instruct` locally via LM Studio guarantees zero API cost, complete data privacy (LGPD Section 9 compliance), and native OpenAI-compatible tool calling. To make an 8B model with a 4,096-token context window perform with 100% reliability, we engineered **automatic type coercion for stringified tool arguments**, **compact high-signal tool output projection**, and **two-stage tool routing + grounded synthesis**. |
| **Interaction Interface** | **Dual Interface: CLI (`cli.py`) + Streamlit Web UI (`app.py`)** | The CLI allows instant terminal verification and single-command testing, while the Streamlit Web UI provides pre-loaded test scenarios and an expandable **Tool Call Inspector** to audit the agent's reasoning in real time. |
| **Conversation History Persistence** | **Session-scoped JSON Persistence (`data/session_history.json`)** | Customer service interactions are inherently multi-turn (e.g., Turn 1: *"Me arrependi da compra, posso devolver?"* → Turn 2: *"Meu pedido é o #8"*). Persisting conversation turns and tool call traces per `session_id` enables seamless follow-ups. |
| **Data Treatment & Sanitization** | **Normalized SQLite (`data/emporio_musica.db`) + Automated Data Quality Detector** | Operational CSVs are loaded into relational tables with accent-insensitive text normalization (`name_norm`), digit-only phone normalization (`phone_digits`), and an automated consistency checker (`data_quality_warning`) that flags catalog contradictions before they reach the customer. |

### System Data Flow
```
Customer Message (CLI / Streamlit)
       │
       ▼
┌───────────────────────────────────────────────────────────┐
│               EmporioAgent Orchestrator                   │
│  • Local LLM: meta-llama-3.1-8b-instruct (LM Studio)      │
│  • Persona System Prompt (Tom — Empório da Música)        │
│  • Persistent Session Memory (data/session_history.json)  │
└──────┬──────────────┬──────────────┬──────────────┬───────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  search_products  get_product   lookup_customer  consult_store
  & simulate_pay   _details      _orders          _policy
       │              │              │              │
       └──────────────┴──────┬───────┴──────────────┘
                             ▼
     ┌───────────────────────────────────────────────┐
     │ SQLite (emporio_musica.db) + Policy Index     │
     │ • 65 Products (with stock & anomaly flags)    │
     │ • 25 Promotions (4 active, 21 expired)        │
     │ • 20 Orders + 22 Order Items + 50 Customers   │
     │ • 9 Structured Sections of políticas_da_loja  │
     └───────────────────────────────────────────────┘
```

---

## 🔍 3. Data Quality Audit & Hidden Edge Cases Handled

During exploratory data analysis of `data/*.csv` and `data/políticas_da_loja.pdf`, we identified and engineered explicit handling for **7 critical data anomalies and business rule traps**:

1. **Unavailable & Discontinued Guitars under R$ 1,000 (`products.csv`):**
   - In category `5` (*Violões*), 14 products have `price_brl <= 1000`: **12 are active with stock > 0**, while **2 cannot be sold**:
     - `product_id=96` (*Giannini GF-3D Dreadnought Sunburst*, R$ 799.90) has `status="active"` but **`stock_quantity = 0`**.
     - `product_id=113` (*Shelby SN-7C 7 Cordas Nylon*, R$ 749.00) has **`status = "discontinued"`** and `stock_quantity = 0`.
   - **How we handle it:** `search_products()` strictly separates `available_products` (`status == 'active' AND stock_quantity > 0`) from `unavailable_or_discontinued_matches`, complying with **Section 7.1 & 7.3** (*"Never confirm availability without checking current stock"*).

2. **Expired Promotion on a Highlighted Product (`Takamine GD20` — `product_id=95`):**
   - `promotions.csv` contains 25 rows, of which **only 4 are active (`is_active = 1`)** (`product_id` `90`, `94`, `121`, `127`) and **21 are expired (`is_active = 0`)**, including `product_id=95` (*Takamine GD20*, 12% OFF *Oferta Especial*, `is_active = 0`).
   - **How we handle it:** `get_product_details()` inspects both active and expired promotions. For the *Takamine GD20*, the agent informs the customer that the previous 12% campaign has expired (Section 7.3), presents the current table price (**R$ 2,199.00**), and applies the **5% PIX discount (R$ 2,089.05)** or **12x interest-free installments of R$ 183.25**.

3. **Non-Cumulative PIX Discount vs. Active Promotions (Section 6.2):**
   - According to Section 6.2, the **5% PIX discount does not stack on top of already promotional prices**, and promotional prices must always be displayed alongside the original price and discount percentage. Our pricing engine enforces this deterministically.

4. **Synthetic Brand/Spec Contradictions in Products `135` to `144` (`products.csv`):**
   - Rows `135–144` contain mismatches between `name`, `description`, and `specs`:
     - `ID 135`: Named *Music Man Bass 1X*, description says *Fender Jazz Bass with Alder body*, specs say *Ash body*.
     - `ID 137`: Named *Yamaha Bass 3X*, description says *5-string Ibanez*, specs say *4 strings*.
     - `ID 139 & 140`: Named *Yamaha Kit 1* / *Pearl Kit 2*, descriptions say *Pearl Export (Poplar)* / *Tama (Birch)*, specs say *Maple*.
     - `ID 142 & 144`: Named *Korg Synth 1 Pro* / *Roland Synth 3 Pro*, descriptions say *Roland 88 keys* / *Yamaha arranger*, specs say *61 keys*.
   - **How we handle it:** `detect_product_inconsistency()` in `src/data_loader.py` automatically flags these records with a `data_quality_warning` during ingestion so the agent warns the customer and offers physical stock verification before purchase.

5. **Empty Categories in Catalog (`categories.csv` vs. `products.csv`):**
   - Categories `6` (*Sopro - Madeiras*), `7` (*Sopro - Metais*), and `8` (*Cordas Orquestrais*) exist in `categories.csv` but have **0 products** in `products.csv`. The agent transparently informs the customer that no items are currently in stock for these categories.

6. **Orders Referencing a `coming_soon` Product (`product_id=130`):**
   - `product_id=130` (*Kala KA-ABP-CTG Barítono Cedar*) has `status="coming_soon"`, yet appears in `order_id=3` and `order_id=14`.

7. **Internal Policy Manual Nuances (`políticas_da_loja.pdf`):**
   - **Phone numbers:** Pages 1–2 list `(67) 3341-4444` (general landline/store) while Page 6 specifies `(67) 3321-4500` as the dedicated WhatsApp customer service channel. Both are indexed and provided clearly.
   - **Credit Card Installments:** Page 3's summary table states *"Minimum installment of R$ 100.00"*, whereas Section 3.1 defines the granular tiered rule (`1x–3x`: min order R$ 50; `4x–6x`: min installment R$ 80; `7x–12x`: min installment R$ 100). We implemented Section 3.1's exact tiered rules in `_compute_installments()`.

---

## 💬 4. Conversation Examples

Full multi-turn conversation logs with JSON tool call traces are available in **[`examples/exemplos_interacao.md`](examples/exemplos_interacao.md)**, covering:
1. **Catalog Search & Stock/Status Filtering:** *"Quais opções de violões disponíveis custando até R$1000?"* + out-of-scope accessory redirection (*cordas, palhetas, capa*).
2. **Price Lookup, Expired vs. Active Promotions & PIX Rule:** *"Quanto custa o Takamine GD20?"* + active solid-top guitar promotions (*Crafter HT-100* & *Taylor 110e*).
3. **Non-Trivial Real-Time Order + Return Policy Evaluation:** *"Me arrependi da minha compra, posso devolver meu pedido?"* evaluated against real orders `#8` (Ana Carolina — eligible within 7 calendar days of delivery) and `#4` (Lucas Mendes — outside 7-day withdrawal, covered by 90-day legal warranty).
4. **Store Address, Opening Hours & Cancelled Order Investigation:** Checking Campo Grande store info and investigating `order_id=19` (cancelled due to unconfirmed boleto payment).
5. **Data Quality Guardrail & Empty Category Handling:** Querying saxophones (0 stock in category 6/7) and `Music Man Bass 1X` (`ID 135` catalog inconsistency disclosure).

---

## 🔮 5. Known Limitations & What I Would Do With More Time

1. **Dense Vector Search for Unstructured Queries:**
   - *Current limitation:* Catalog search uses normalized token matching + structured SQL filters, and policy retrieval uses section-level keyword/TF scoring. While ideal for this 65-product dataset and 8-page manual (and fast within a 4,096-token local context window), a 50,000-SKU catalog would require dense embeddings.
   - *Next step:* Integrate local dense embeddings (`text-embedding-nomic-embed-text-v1.5` via LM Studio `/v1/embeddings` + `sqlite-vec`) with Reciprocal Rank Fusion (RRF).
2. **Customer Authentication & LGPD Guardrails:**
   - *Current limitation:* Looking up an order by `order_id` or name returns customer details directly for demonstration purposes.
   - *Next step:* Require two-factor verification (e.g., matching both `order_id` + last 4 digits of phone/email) before exposing tracking codes or personal data, in strict compliance with Section 9 (LGPD).
3. **Transactional Write Actions (Human-in-the-Loop):**
   - *Current limitation:* The agent operates in read-only mode over `orders` and `products`.
   - *Next step:* Add write tools (`create_return_ticket`, `register_complaint_24h_sla`, `reserve_cart`) backed by a human-in-the-loop approval queue for store attendants.
4. **Automated LLM-as-a-Judge Evaluation Pipeline:**
   - *Next step:* Expand `tests/test_agent_and_tools.py` with an automated evaluation dataset measuring Faithfulness, Tool Selection Accuracy, and Policy Compliance across 50+ adversarial prompts (including prompt injection attempts).

---

## 🤖 6. Use of AI Coding Assistants (Workflow Transparency)

In accordance with the challenge instructions regarding AI coding assistants:
- **Tool Used:** **Google Antigravity (Agentic IDE)**.
- **How It Was Used in My Workflow:**
  1. **Exploratory Data & Policy Auditing:** I used the assistant to rapidly cross-reference all 6 CSV files against the 8 pages of `políticas_da_loja.pdf`, uncovering the synthetic data contradictions in products `135–144`, the inactive promotions in `promotions.csv`, and the stock/discontinued edge cases in guitars under R$ 1,000.
  2. **Architecture & Deterministic Tool Design:** Instead of asking AI to generate a generic chatbot, I designed a domain-specific 5-tool architecture where business math (tiered credit card installments, non-cumulative PIX discounts, and 7/30/90-day CDC return windows) is computed deterministically in Python (`src/tools.py`) rather than left to LLM arithmetic.
  3. **Local LLM Calibration & Test-Driven Verification:** Used the assistant to test and calibrate `meta-llama-3.1-8b-instruct` running locally in LM Studio (handling stringified tool arguments and compacting tool payloads for the 4096-token context window) and to scaffold automated unit tests (`tests/test_agent_and_tools.py`).
