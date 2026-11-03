"""
Data Ingestion, Sanitization & Policy Indexing Engine for Empório da Música.

Loads operational CSV tables into a normalized SQLite database, executes automated
data quality checks (flagging synthetic catalog inconsistencies in products 135-144,
stock/status edge cases, and active vs. expired promotions), and indexes the store
policy manual (`políticas_da_loja.pdf`) into structured, searchable sections.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "emporio_musica.db"


def normalize_text(text: str) -> str:
    """Remove accents and lowercase text for accent-insensitive search."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def normalize_digits(text: str) -> str:
    """Keep only digits from a phone number or document string."""
    return re.sub(r"\D", "", str(text or ""))


def detect_product_inconsistency(name: str, description: str, specs_raw: str) -> Optional[str]:
    """
    Detect catalog inconsistencies between product `name`, `description`, and `specs`.

    In the provided dataset, products 135-144 contain synthetic mismatches
    (e.g., Name='Music Man Bass 1X', Description='Fender Jazz Bass com corpo em Alder',
    Specs='{"body": "Ash"}'; or Name='Teclado Korg Synth 1 Pro', Description='Roland 88 teclas',
    Specs='{"keys": "61"}').
    """
    brands = [
        "Yamaha", "Tagima", "Giannini", "Rozini", "Shelby", "Crafter",
        "Martin", "Taylor", "Takamine", "Kala", "Ohana", "Kalani",
        "Fender", "Gibson", "Ibanez", "PRS", "Music Man", "Pearl",
        "Tama", "Korg", "Roland", "Nord"
    ]
    name_lower = name.lower()
    desc_lower = description.lower()

    name_brands = [b for b in brands if b.lower() in name_lower]
    desc_brands = [b for b in brands if b.lower() in desc_lower]

    warnings: List[str] = []
    if name_brands and desc_brands and set(name_brands) != set(desc_brands):
        warnings.append(
            f"Divergência de marca no cadastro: título indica '{', '.join(name_brands)}', "
            f"mas a descrição menciona '{', '.join(desc_brands)}'."
        )

    try:
        specs = json.loads(specs_raw) if specs_raw else {}
    except Exception:
        specs = {}

    if "5 cordas" in desc_lower and str(specs.get("strings")) == "4":
        warnings.append("Divergência de especificações: descrição cita 5 cordas, mas ficha técnica indica 4 cordas.")
    if "88 teclas" in desc_lower and str(specs.get("keys")) == "61":
        warnings.append("Divergência de especificações: descrição cita 88 teclas, mas ficha técnica indica 61 teclas.")
    if "alder" in desc_lower and str(specs.get("body", "")).lower() == "ash":
        warnings.append("Divergência de madeira: descrição cita corpo em Alder, mas ficha técnica indica Ash.")

    return " ".join(warnings) if warnings else None


def init_database(db_path: Path = DEFAULT_DB_PATH, data_dir: Path = DATA_DIR) -> sqlite3.Connection:
    """
    Create and populate the SQLite database from `data/*.csv`.
    Returns an open sqlite3.Connection with Row factory enabled.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.executescript(
        """
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS promotions;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS categories;

        CREATE TABLE categories (
            category_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            phone TEXT,
            phone_digits TEXT,
            email TEXT,
            city TEXT,
            city_norm TEXT
        );

        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            price_brl REAL NOT NULL,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            description TEXT,
            description_norm TEXT,
            stock_quantity INTEGER NOT NULL,
            status TEXT NOT NULL,
            specs TEXT,
            created_at TEXT,
            data_quality_warning TEXT,
            FOREIGN KEY (category_id) REFERENCES categories(category_id)
        );

        CREATE TABLE promotions (
            promotion_id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            discount_percent REAL NOT NULL,
            description TEXT,
            is_active INTEGER NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );

        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL,
            total_brl REAL NOT NULL,
            payment_method TEXT,
            tracking_code TEXT,
            estimated_delivery TEXT,
            notes TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );
        """
    )

    # 1. Load categories.csv
    cat_file = data_dir / "desafio_tecnico_ai_eng - categories.csv"
    with open(cat_file, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT INTO categories VALUES (?, ?, ?, ?)",
                (
                    int(row["category_id"]),
                    row["name"].strip(),
                    normalize_text(row["name"]),
                    row["description"].strip(),
                ),
            )

    # 2. Load customers.csv
    cust_file = data_dir / "desafio_tecnico_ai_eng - customers.csv"
    with open(cust_file, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(row["customer_id"]),
                    row["name"].strip(),
                    normalize_text(row["name"]),
                    row["phone"].strip(),
                    normalize_digits(row["phone"]),
                    row["email"].strip().lower(),
                    row["city"].strip(),
                    normalize_text(row["city"]),
                ),
            )

    # 3. Load products.csv
    prod_file = data_dir / "desafio_tecnico_ai_eng - products.csv"
    with open(prod_file, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            warning = detect_product_inconsistency(
                row["name"], row["description"], row["specs"]
            )
            cur.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(row["product_id"]),
                    float(row["price_brl"]),
                    row["name"].strip(),
                    normalize_text(row["name"]),
                    int(row["category_id"]),
                    row["description"].strip(),
                    normalize_text(row["description"]),
                    int(row["stock_quantity"]),
                    row["status"].strip(),
                    row["specs"].strip(),
                    row["created_at"].strip(),
                    warning,
                ),
            )

    # 4. Load promotions.csv
    promo_file = data_dir / "desafio_tecnico_ai_eng - promotions.csv"
    with open(promo_file, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT INTO promotions VALUES (?, ?, ?, ?, ?)",
                (
                    int(row["promotion_id"]),
                    int(row["product_id"]),
                    float(row["discount_percent"]),
                    row["description"].strip(),
                    int(row["is_active"]),
                ),
            )

    # 5. Load orders.csv
    orders_file = data_dir / "desafio_tecnico_ai_eng - orders.csv"
    with open(orders_file, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(row["order_id"]),
                    int(row["customer_id"]),
                    row["order_date"].strip(),
                    row["status"].strip(),
                    float(row["total_brl"]),
                    row["payment_method"].strip(),
                    row["tracking_code"].strip() if row["tracking_code"] else None,
                    row["estimated_delivery"].strip() if row["estimated_delivery"] else None,
                    row["notes"].strip() if row["notes"] else None,
                ),
            )

    # 6. Load order_items.csv
    items_file = data_dir / "desafio_tecnico_ai_eng - order_items.csv"
    with open(items_file, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT INTO order_items (order_id, quantity, product_id) VALUES (?, ?, ?)",
                (
                    int(row["order_id"]),
                    int(row["quantity"]),
                    int(row["product_id"]),
                ),
            )

    conn.commit()
    return conn


# Structured Store Policy Sections extracted from `data/políticas_da_loja.pdf` (v2.1 - June 2025)
STORE_POLICY_SECTIONS: List[Dict[str, Any]] = [
    {
        "section_id": "1",
        "title": "1. Sobre a Empório da Música, Missão, Endereço, Contato e Escopo",
        "keywords": [
            "sobre", "endereco", "localizacao", "campo grande", "rua 14 de maio",
            "telefone", "whatsapp", "email", "cnpj", "acessorios", "cordas",
            "palhetas", "cabos", "cases", "pedais", "amplificadores", "escopo"
        ],
        "content": (
            "Razão Social: Empório da Música Instrumentos Musicais Ltda. | Nome Fantasia: Empório da Música | "
            "CNPJ: 12.345.678/0001-90 | Fundação: 2008 em Campo Grande/MS.\n"
            "Endereço Físico: Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333.\n"
            "Telefone Fixo / Geral: (67) 3341-4444 | Canal Principal de Atendimento WhatsApp: (67) 3321-4500.\n"
            "E-mail: contato@emporiodamusica.com.br.\n"
            "Escopo Exclusivo: Trabalhamos EXCLUSIVAMENTE com instrumentos musicais (guitarras, baixos, violões, "
            "baterias, teclados, instrumentos de sopro, cordas orquestrais e ukuleles). NÃO comercializamos acessórios "
            "avulsos como cordas, encordoamentos, palhetas, cabos, cases/capas, pedais ou amplificadores."
        ),
    },
    {
        "section_id": "2",
        "title": "2. Horário de Funcionamento (Loja Física e WhatsApp)",
        "keywords": [
            "horario", "funcionamento", "aberto", "fechado", "sabado", "domingo",
            "feriado", "expediente", "atendimento", "horas"
        ],
        "content": (
            "Horário de Funcionamento (Presencial e Atendimento via WhatsApp):\n"
            "- Segunda a Sexta-feira: 09:00 às 18:00\n"
            "- Sábado: 09:00 às 13:00\n"
            "- Domingo e Feriados: Fechado\n"
            "Observação: Em datas especiais (Black Friday, Aniversário da Loja, Natal), o horário pode ser estendido. "
            "Fora do expediente, o assistente virtual informa o horário de retorno."
        ),
    },
    {
        "section_id": "3",
        "title": "3. Formas de Pagamento e Regras de Parcelamento",
        "keywords": [
            "pagamento", "pix", "desconto", "cartao", "credito", "debito",
            "boleto", "parcelamento", "parcelas", "sem juros", "combinacao"
        ],
        "content": (
            "Formas de Pagamento (compras presenciais e online):\n"
            "1. PIX: Pagamento à vista com 5% de desconto sobre o preço de tabela (NÃO cumulativo com promoções ativas).\n"
            "2. Cartão de Débito: Pagamento à vista (todas as bandeiras aceitas).\n"
            "3. Cartão de Crédito: Até 12x sem juros, respeitando as regras escalonadas de parcela mínima (Seção 3.1):\n"
            "   - Até 3x sem juros: sem valor mínimo de parcela (exceto compras abaixo de R$ 50,00).\n"
            "   - De 4x a 6x sem juros: parcela mínima de R$ 80,00.\n"
            "   - De 7x a 12x sem juros: parcela mínima de R$ 100,00.\n"
            "4. Boleto Bancário: Pagamento à vista (compensação em até 3 dias úteis).\n"
            "5. Combinação de formas de pagamento: Permitida (ex.: PIX + cartão de crédito) para compras acima de R$ 2.000,00."
        ),
    },
    {
        "section_id": "4",
        "title": "4. Política de Trocas, Devoluções e Direito de Arrependimento",
        "keywords": [
            "troca", "devolucao", "arrependimento", "arrependi", "devolver",
            "reembolso", "defeito", "preferencia", "cor", "modelo", "prazo",
            "7 dias", "30 dias", "boquilhas", "personalizacao", "venda final"
        ],
        "content": (
            "Política de Trocas e Devoluções (CDC - Lei nº 8.078/90):\n"
            "- 4.1 Direito de Arrependimento (Compras Online): Solicitação em até 7 (sete) dias corridos após o recebimento "
            "do produto, sem necessidade de justificativa. O produto deve estar na embalagem original, sem sinais de uso, "
            "com todos os acessórios e manuais. Reembolso na mesma forma de pagamento original em até 10 dias úteis. "
            "O frete de devolução é por conta da loja em caso de arrependimento.\n"
            "- 4.2 Trocas por Defeito: Produtos com defeito de fabricação podem ser trocados na loja em até 30 (trinta) dias "
            "corridos após a compra. Após 30 dias, acionar a garantia com o fabricante (a loja pode intermediar mediante "
            "solicitação). Danos por mau uso, quedas, umidade excessiva ou modificações não autorizadas não são cobertos.\n"
            "- 4.3 Trocas por Preferência (cor, modelo, tamanho): Permitidas em até 7 dias corridos, mediante disponibilidade "
            "do produto desejado, em perfeito estado e na embalagem original. Diferenças de valor são cobradas ou reembolsadas.\n"
            "- 4.4 Itens Não Elegíveis para Troca: Instrumentos com personalização/ajustes sob encomenda (setup, regulagem "
            "especial), produtos de liquidação com aviso explícito de 'venda final', e boquilhas de instrumentos de sopro (higiene)."
        ),
    },
    {
        "section_id": "5",
        "title": "5. Política de Frete, Entregas e Código de Rastreamento",
        "keywords": [
            "frete", "entrega", "prazo", "motoboy", "correios", "pac", "sedex",
            "jadlog", "rastreamento", "rastreio", "seguro", "avaria", "gratis"
        ],
        "content": (
            "Política de Frete e Entregas:\n"
            "- 5.1 Região Metropolitana de Campo Grande: Frete GRÁTIS para pedidos acima de R$ 500,00. Para pedidos abaixo "
            "de R$ 500,00, taxa fixa de R$ 35,00. Prazo de 1 a 3 dias úteis via motoboy próprio (cliente é contactado por "
            "telefone antes da entrega).\n"
            "- 5.2 Outras Cidades: Envio via Correios ou Jadlog com rastreamento e seguro incluídos:\n"
            "  * PAC (Correios): 5 a 12 dias úteis\n"
            "  * SEDEX (Correios): 2 a 5 dias úteis\n"
            "  * Jadlog (.package): 3 a 8 dias úteis\n"
            "  Instrumentos de grande porte (baterias acústicas, pianos digitais, contrabaixos) podem exigir frete especial "
            "com cotação individual. Em caso de avaria no transporte, recusar o recebimento e contatar a loja imediatamente.\n"
            "- 5.3 Código de Rastreamento: Enviado por e-mail e WhatsApp assim que despachado."
        ),
    },
    {
        "section_id": "6",
        "title": "6. Promoções e Descontos (Regras de Não-Cumulatividade)",
        "keywords": [
            "promocao", "promocoes", "desconto", "cumulativo", "black friday",
            "aniversario", "queima de estoque", "semana do musico", "volta as aulas"
        ],
        "content": (
            "Regras de Promoções e Descontos:\n"
            "- Campanhas periódicas: Aniversário da Loja (Agosto, 10%-25%), Black Friday (Novembro, 15%-30%), "
            "Volta às Aulas (Fevereiro), Queima de Estoque, Semana do Músico (22 de novembro).\n"
            "- Não-Cumulatividade: Promoções NÃO são cumulativas. O desconto de 5% no PIX NÃO se aplica sobre preços já promocionais.\n"
            "- Estoque: Sujeitas à disponibilidade de estoque (sem direito a rain check/reserva de preço se esgotar).\n"
            "- Transparência obrigatória: Preços promocionais devem SEMPRE ser apresentados junto ao preço original e ao "
            "percentual de desconto."
        ),
    },
    {
        "section_id": "7",
        "title": "7. Diretrizes de Atendimento e Situações Especiais",
        "keywords": [
            "diretrizes", "tom de voz", "fora de estoque", "esgotado",
            "descontinuado", "promocao expirada", "reclamacao", "24 horas"
        ],
        "content": (
            "Diretrizes e Situações Especiais no Atendimento:\n"
            "- Tom de voz: Informal mas profissional, acolhedor, como um amigo que entende de música.\n"
            "- Produto fora de estoque: Informar que está temporariamente indisponível e sugerir alternativas disponíveis.\n"
            "- Produto descontinuado: Informar que não faz mais parte do catálogo e oferecer modelos equivalentes.\n"
            "- Promoção expirada: Verificar se está ativa no sistema. Se vencida, informar com transparência e apresentar o preço atual.\n"
            "- Reclamação: Ouvir com empatia, registrar e encaminhar ao responsável (prazo de retorno: 24 horas úteis)."
        ),
    },
    {
        "section_id": "8",
        "title": "8. Garantia Legal e do Fabricante",
        "keywords": [
            "garantia", "90 dias", "fabricante", "trastes", "desgaste", "mau uso", "luthier"
        ],
        "content": (
            "Política de Garantia:\n"
            "- 8.1 Garantia Legal (CDC): 90 dias corridos contra defeitos de fabricação a partir do recebimento.\n"
            "- 8.2 Garantia do Fabricante: 6 meses a 2 anos adicionais conforme certificado do fabricante.\n"
            "- 8.3 Exclusões da Garantia: Desgaste natural (trastes, cordas, feltros, palhetas de sopro), mau uso, queda, "
            "condições climáticas extremas, reparos por terceiros não autorizados e danos meramente estéticos."
        ),
    },
    {
        "section_id": "9",
        "title": "9. Privacidade e Proteção de Dados (LGPD)",
        "keywords": [
            "lgpd", "privacidade", "dados pessoais", "exclusao", "marketing", "compartilhamento"
        ],
        "content": (
            "Privacidade e LGPD (Lei nº 13.709/2018):\n"
            "- Dados coletados (nome, telefone, e-mail, endereço) são usados exclusivamente para processamento/entrega de "
            "pedidos, status/rastreamento, promoções (com consentimento explícito) e obrigações legais/fiscais.\n"
            "- Dados não são compartilhados com terceiros para marketing. O cliente pode solicitar exclusão a qualquer "
            "momento via WhatsApp ou e-mail."
        ),
    },
]


def extract_raw_pdf_text(pdf_path: Path = DATA_DIR / "políticas_da_loja.pdf") -> str:
    """Extract raw text from `políticas_da_loja.pdf` using pypdf if available."""
    if not pdf_path.exists():
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except Exception:
        return ""
