"""
Deterministic Function-Calling Tools for the Empório da Música AI Agent.

Implements 5 grounded tools backed by SQLite and the indexed Store Policy Manual:
1. `search_products` — Catalog search with stock/status filtering, active/expired promos, and PIX/installments.
2. `get_product_details` — Deep inspection of an instrument, promo history, and in-stock alternatives.
3. `lookup_customer_orders` — Order status, tracking, cancellation notes, and CDC return/exchange windows.
4. `simulate_payment_and_shipping` — Exact installment rules (Section 3.1) and shipping rates (Section 5).
5. `consult_store_policy` — Section-grounded retrieval from `políticas_da_loja.pdf`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.data_loader import (
    DEFAULT_DB_PATH,
    STORE_POLICY_SECTIONS,
    init_database,
    normalize_digits,
    normalize_text,
)

ACCESSORY_KEYWORDS = [
    "corda", "cordas", "encordoamento", "palheta", "palhetas", "cabo", "cabos",
    "case", "cases", "capa", "bag", "pedal", "pedais", "pedaleira", "amplificador",
    "amplificadores", "amp", "cubo", "suporte", "estalante", "correia", "capotraste",
    "boquilha", "boquilhas", "baqueta", "baquetas", "afinador avulso"
]


def _compute_installments(amount_brl: float) -> Dict[str, Any]:
    """
    Compute valid interest-free credit card installments according to Policy Section 3.1:
    - Up to 3x: interest-free, no minimum installment (except purchases below R$ 50.00).
    - 4x to 6x: interest-free, minimum installment of R$ 80.00.
    - 7x to 12x: interest-free, minimum installment of R$ 100.00.
    - Combined payment (e.g. PIX + Card): allowed for purchases above R$ 2,000.00.
    """
    if amount_brl < 50.0:
        return {
            "max_installments": 1,
            "installment_value_brl": round(amount_brl, 2),
            "summary": f"1x de R$ {amount_brl:,.2f} (compras abaixo de R$ 50,00 não parcelam - Seção 3.1)",
            "valid_options": [{"installments": 1, "value_brl": round(amount_brl, 2)}],
            "combined_payment_allowed": False,
        }

    valid_options: List[Dict[str, Any]] = []
    for n in range(1, 13):
        val = amount_brl / n
        if n <= 3:
            valid_options.append({"installments": n, "value_brl": round(val, 2)})
        elif 4 <= n <= 6 and val >= 80.0:
            valid_options.append({"installments": n, "value_brl": round(val, 2)})
        elif 7 <= n <= 12 and val >= 100.0:
            valid_options.append({"installments": n, "value_brl": round(val, 2)})

    best = valid_options[-1]
    return {
        "max_installments": best["installments"],
        "installment_value_brl": best["value_brl"],
        "summary": f"até {best['installments']}x sem juros de R$ {best['value_brl']:,.2f}",
        "valid_options": valid_options,
        "combined_payment_allowed": amount_brl > 2000.0,
    }


def _enrich_product_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    """Enrich a product row with category name, parsed specs, promotions, and pricing rules."""
    cur = conn.cursor()
    pid = row["product_id"]
    orig_price = float(row["price_brl"])

    cur.execute("SELECT name FROM categories WHERE category_id = ?", (row["category_id"],))
    cat_row = cur.fetchone()
    cat_name = cat_row["name"] if cat_row else "Desconhecida"

    cur.execute(
        "SELECT promotion_id, discount_percent, description, is_active FROM promotions WHERE product_id = ?",
        (pid,),
    )
    promo_rows = cur.fetchall()

    active_promo = None
    expired_promos = []
    for pr in promo_rows:
        p_info = {
            "promotion_id": pr["promotion_id"],
            "discount_percent": float(pr["discount_percent"]),
            "campaign": pr["description"],
            "promotional_price_brl": round(orig_price * (1.0 - float(pr["discount_percent"]) / 100.0), 2),
        }
        if int(pr["is_active"]) == 1:
            active_promo = p_info
        else:
            expired_promos.append(p_info)

    if active_promo:
        effective_price = active_promo["promotional_price_brl"]
        pix_price = effective_price
        pix_note = (
            f"Preço promocional ativo ({active_promo['discount_percent']:.0f}% OFF - {active_promo['campaign']}). "
            "Conforme Seção 6.2, o desconto de 5% do PIX não é cumulativo com promoções ativas."
        )
    else:
        effective_price = orig_price
        pix_price = round(orig_price * 0.95, 2)
        pix_note = "5% de desconto para pagamento à vista via PIX (Seção 3)."

    installments = _compute_installments(effective_price)

    try:
        specs = json.loads(row["specs"]) if row["specs"] else {}
    except Exception:
        specs = {}

    return {
        "product_id": pid,
        "name": row["name"],
        "category_id": row["category_id"],
        "category_name": cat_name,
        "status": row["status"],
        "stock_quantity": int(row["stock_quantity"]),
        "is_available_now": row["status"] == "active" and int(row["stock_quantity"]) > 0,
        "original_price_brl": orig_price,
        "effective_price_brl": effective_price,
        "pix_price_brl": pix_price,
        "pix_rule_note": pix_note,
        "active_promotion": active_promo,
        "expired_promotions": expired_promos,
        "installment_plan": installments["summary"],
        "max_installments": installments["max_installments"],
        "description": row["description"],
        "specs": specs,
        "data_quality_warning": row["data_quality_warning"],
    }


class EmporioTools:
    """Stateful wrapper around the Empório da Música SQLite database and policy index."""

    def __init__(self, conn: Optional[sqlite3.Connection] = None) -> None:
        self.conn = conn or init_database(DEFAULT_DB_PATH)

    def search_products(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        strings_type: Optional[str] = None,
        has_electronics: Optional[bool] = None,
        only_active_promotions: bool = False,
    ) -> Dict[str, Any]:
        """
        Search the musical instrument catalog with strict stock and status separation.

        Args:
            query: Free-text search term (brand, model, instrument type, or keyword).
            category: Category name or filter (e.g., 'Violões', 'Guitarras', 'Baixos', 'Baterias', 'Teclados', 'Ukuleles').
            max_price: Maximum price in BRL (evaluates against effective price).
            min_price: Minimum price in BRL.
            strings_type: Optional filter for string material ('nylon' or 'steel').
            has_electronics: Optional filter for electroacoustic/pickup instruments (True/False).
            only_active_promotions: If True, returns only products with currently active promotions (is_active=1).
        """
        q_norm = normalize_text(query or "")
        cat_norm = normalize_text(category or "")

        # Check if customer is asking for out-of-scope accessories (Policy 1 & 7.1)
        out_of_scope_alert = None
        for kw in ACCESSORY_KEYWORDS:
            if kw in q_norm.split() or (len(kw) > 4 and kw in q_norm):
                # Ensure it's not "7 cordas" or "cordas de nylon/aço" referring to guitars
                if kw in ("corda", "cordas") and any(
                    w in q_norm for w in ["7 cordas", "violao", "nylon", "aco", "orquestrais"]
                ):
                    continue
                out_of_scope_alert = (
                    "ATENÇÃO (Política 1 e 7.1): A Empório da Música trabalha EXCLUSIVAMENTE com "
                    "instrumentos musicais. Não comercializamos acessórios avulsos (cordas, palhetas, "
                    "cabos, cases, pedais, amplificadores ou boquilhas). Redirecione o cliente "
                    "educadamente informando nosso escopo exclusivo de instrumentos."
                )
                break

        cur = self.conn.cursor()

        # Check if user searched for an empty registered category (Sopro or Cordas Orquestrais)
        empty_category_note = None
        for empty_term in ["sopro", "flauta", "clarinete", "saxofone", "trompete", "trombone", "violino", "violoncelo", "orquestra"]:
            if empty_term in q_norm or empty_term in cat_norm:
                empty_category_note = (
                    "Nota de Catálogo: Embora as categorias 'Instrumentos de Sopro (Madeiras/Metais)' e "
                    "'Cordas Orquestrais' façam parte da loja, no momento não há itens cadastrados com estoque "
                    "no sistema para essas categorias."
                )
                break

        cur.execute("SELECT * FROM products ORDER BY price_brl ASC")
        all_rows = cur.fetchall()

        # Map category filter
        matched_cat_ids: Optional[List[int]] = None
        if cat_norm:
            cur.execute("SELECT category_id, name_norm FROM categories")
            cat_matches = [
                r["category_id"]
                for r in cur.fetchall()
                if cat_norm in r["name_norm"] or r["name_norm"] in cat_norm
            ]
            # Handle singular/plural aliases
            if not cat_matches:
                alias_map = {
                    "violao": [5], "violoes": [5],
                    "guitarra": [1], "guitarras": [1],
                    "baixo": [2], "baixos": [2], "contrabaixo": [2],
                    "bateria": [3], "baterias": [3], "percussao": [3],
                    "teclado": [4], "teclados": [4], "piano": [4], "sintetizador": [4],
                    "ukulele": [9], "ukuleles": [9],
                }
                for k, v in alias_map.items():
                    if k in cat_norm:
                        cat_matches.extend(v)
            if cat_matches:
                matched_cat_ids = list(set(cat_matches))

        available_results: List[Dict[str, Any]] = []
        unavailable_results: List[Dict[str, Any]] = []

        for row in all_rows:
            if matched_cat_ids is not None and row["category_id"] not in matched_cat_ids:
                continue

            item = _enrich_product_row(self.conn, row)

            # Query text matching
            if q_norm:
                # Ignore generic words that already map to categories
                tokens = [
                    t for t in q_norm.split()
                    if t not in {"de", "da", "do", "com", "para", "ate", "disponiveis", "opcoes", "quero", "tem"}
                ]
                searchable = normalize_text(
                    f"{item['name']} {item['category_name']} {item['description']} {json.dumps(item['specs'])}"
                )
                # Synonym normalization (violao <-> violoes)
                norm_tokens = []
                for t in tokens:
                    if t == "violoes":
                        norm_tokens.append("violao")
                    elif t == "guitarras":
                        norm_tokens.append("guitarra")
                    elif t == "baixos":
                        norm_tokens.append("baixo")
                    elif t == "ukuleles":
                        norm_tokens.append("ukulele")
                    elif t == "teclados":
                        norm_tokens.append("teclado")
                    elif t == "baterias":
                        norm_tokens.append("bateria")
                    else:
                        norm_tokens.append(t)

                if norm_tokens and not all(t in searchable for t in norm_tokens):
                    continue

            # Price filters (check both original and effective promotional price)
            if max_price is not None and item["effective_price_brl"] > float(max_price) and item["original_price_brl"] > float(max_price):
                continue
            if min_price is not None and item["effective_price_brl"] < float(min_price):
                continue

            # Specs filters
            if strings_type:
                st_norm = normalize_text(strings_type)
                prod_strings = normalize_text(str(item["specs"].get("strings", "")))
                if st_norm in ("aco", "steel") and prod_strings != "steel" and "aco" not in normalize_text(item["name"]):
                    continue
                if st_norm == "nylon" and prod_strings != "nylon" and "nylon" not in normalize_text(item["name"]):
                    continue

            if has_electronics is not None:
                elec_val = str(item["specs"].get("electronics", "")).lower()
                is_elec = elec_val == "yes" or "eletrico" in normalize_text(item["name"])
                if has_electronics != is_elec:
                    continue

            if only_active_promotions and not item["active_promotion"]:
                continue

            if item["is_available_now"]:
                available_results.append(item)
            else:
                unavailable_results.append(item)

        return {
            "total_available_in_stock": len(available_results),
            "available_products": available_results,
            "unavailable_or_discontinued_matches": unavailable_results,
            "out_of_scope_accessory_alert": out_of_scope_alert,
            "empty_category_note": empty_category_note,
            "policy_reminder": (
                "Apresente apenas produtos 'available_products' como disponíveis para compra imediata. "
                "Se houver itens em 'unavailable_or_discontinued_matches', informe com transparência que estão "
                "temporariamente sem estoque (stock=0) ou descontinuados/em breve (Seção 7.3)."
            ),
        }

    def get_product_details(
        self,
        product_name_or_id: str,
    ) -> Dict[str, Any]:
        """
        Retrieve full details, stock, active/expired promotions, and similar alternatives for a specific product.

        Args:
            product_name_or_id: Product ID (e.g. '95') or name/model (e.g. 'Takamine GD20', 'Martin D-28').
        """
        cur = self.conn.cursor()
        target_row = None

        if str(product_name_or_id).strip().isdigit():
            cur.execute("SELECT * FROM products WHERE product_id = ?", (int(str(product_name_or_id).strip()),))
            target_row = cur.fetchone()

        if not target_row:
            q_norm = normalize_text(product_name_or_id)
            cur.execute("SELECT * FROM products")
            all_rows = cur.fetchall()
            # Try exact substring first, then token overlap
            for r in all_rows:
                if q_norm in r["name_norm"]:
                    target_row = r
                    break
            if not target_row:
                tokens = [t for t in q_norm.split() if len(t) > 1]
                best_score = 0
                for r in all_rows:
                    score = sum(1 for t in tokens if t in r["name_norm"] or t in r["description_norm"])
                    if score > best_score:
                        best_score = score
                        target_row = r
                if best_score == 0:
                    target_row = None

        if not target_row:
            return {
                "found": False,
                "message": f"Nenhum instrumento encontrado para '{product_name_or_id}'.",
            }

        product = _enrich_product_row(self.conn, target_row)

        # Find up to 3 in-stock alternatives in the same category with close price
        cur.execute(
            """
            SELECT * FROM products
            WHERE category_id = ? AND product_id != ? AND status = 'active' AND stock_quantity > 0
            ORDER BY ABS(price_brl - ?) ASC
            LIMIT 3
            """,
            (product["category_id"], product["product_id"], product["original_price_brl"]),
        )
        alternatives = [_enrich_product_row(self.conn, r) for r in cur.fetchall()]

        shipping_cg = (
            "Frete GRÁTIS para a Região Metropolitana de Campo Grande (pedidos acima de R$ 500,00 - Seção 5.1)"
            if product["effective_price_brl"] >= 500.0
            else "Taxa fixa de R$ 35,00 para a Região Metropolitana de Campo Grande (pedidos abaixo de R$ 500,00 - Seção 5.1)"
        )

        return {
            "found": True,
            "product": product,
            "shipping_campo_grande_note": shipping_cg,
            "similar_in_stock_alternatives": alternatives,
        }

    def lookup_customer_orders(
        self,
        order_id: Optional[int] = None,
        customer_query: Optional[str] = None,
        reference_date: str = "2026-03-25",
    ) -> Dict[str, Any]:
        """
        Look up orders by order_id or customer identifier (name, email, or phone) and evaluate return/exchange policies.

        Args:
            order_id: Numeric order ID (e.g. 1 to 20).
            customer_query: Customer name, email, or phone number.
            reference_date: Current reference date in YYYY-MM-DD format for calculating 7-day and 30-day windows.
        """
        cur = self.conn.cursor()
        matched_orders: List[sqlite3.Row] = []

        if order_id is not None:
            cur.execute("SELECT * FROM orders WHERE order_id = ?", (int(order_id),))
            matched_orders = cur.fetchall()
        elif customer_query:
            q_norm = normalize_text(customer_query)
            q_digits = normalize_digits(customer_query)
            cur.execute("SELECT * FROM customers")
            cust_ids = []
            for c in cur.fetchall():
                if (
                    (q_norm and q_norm in c["name_norm"])
                    or (q_norm and q_norm in c["email"])
                    or (len(q_digits) >= 4 and q_digits in c["phone_digits"])
                ):
                    cust_ids.append(c["customer_id"])
            if cust_ids:
                placeholders = ",".join("?" for _ in cust_ids)
                cur.execute(
                    f"SELECT * FROM orders WHERE customer_id IN ({placeholders}) ORDER BY order_date DESC",
                    cust_ids,
                )
                matched_orders = cur.fetchall()

        if not matched_orders:
            return {
                "found": False,
                "message": (
                    "Nenhum pedido localizado com os dados informados. Solicite ao cliente o número do pedido "
                    "(order_id), nome completo, e-mail ou telefone cadastrado."
                ),
            }

        try:
            ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
        except Exception:
            ref_dt = datetime(2026, 3, 25)

        results = []
        for ord_row in matched_orders:
            cur.execute("SELECT * FROM customers WHERE customer_id = ?", (ord_row["customer_id"],))
            cust = cur.fetchone()

            cur.execute(
                """
                SELECT oi.quantity, p.product_id, p.name, p.price_brl, p.category_id, p.status AS product_status
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                WHERE oi.order_id = ?
                """,
                (ord_row["order_id"],),
            )
            items = [dict(r) for r in cur.fetchall()]

            order_dt = datetime.strptime(ord_row["order_date"], "%Y-%m-%d")
            deliv_str = ord_row["estimated_delivery"]
            deliv_dt = datetime.strptime(deliv_str, "%Y-%m-%d") if deliv_str else None

            # Evaluate Policy 4.1 (7 days from delivery for withdrawal) & 4.2 (30 days from purchase for defect)
            withdrawal_deadline = (deliv_dt + timedelta(days=7)).strftime("%Y-%m-%d") if deliv_dt else None
            defect_store_deadline = (order_dt + timedelta(days=30)).strftime("%Y-%m-%d")
            legal_warranty_deadline = (
                (deliv_dt + timedelta(days=90)).strftime("%Y-%m-%d")
                if deliv_dt
                else (order_dt + timedelta(days=90)).strftime("%Y-%m-%d")
            )

            status = ord_row["status"]
            if status == "delivered" and deliv_dt:
                days_since_delivery = (ref_dt - deliv_dt).days
                days_since_order = (ref_dt - order_dt).days
                eligibility = {
                    "reference_date_used": ref_dt.strftime("%Y-%m-%d"),
                    "days_since_delivery": days_since_delivery,
                    "days_since_purchase": days_since_order,
                    "withdrawal_7d_deadline": withdrawal_deadline,
                    "is_within_7d_withdrawal_or_preference": days_since_delivery <= 7,
                    "defect_30d_store_deadline": defect_store_deadline,
                    "is_within_30d_defect_exchange": days_since_order <= 30,
                    "legal_warranty_90d_deadline": legal_warranty_deadline,
                    "is_within_90d_legal_warranty": days_since_delivery <= 90,
                    "policy_guidance": (
                        "Se o cliente desejar devolver por arrependimento (compras online - Seção 4.1) ou trocar por "
                        f"preferência (Seção 4.3), o prazo legal é de 7 dias corridos após o recebimento (data limite: "
                        f"{withdrawal_deadline}). Para troca direta na loja por defeito de fabricação (Seção 4.2), o "
                        f"prazo é de 30 dias corridos após a compra (data limite: {defect_store_deadline}), além da "
                        f"garantia legal de 90 dias (até {legal_warranty_deadline}) e garantia do fabricante (6m a 2 anos)."
                    ),
                }
            elif status in ("pending", "confirmed", "shipped"):
                eligibility = {
                    "policy_guidance": (
                        f"O pedido está com status '{status}' (ainda não entregue). Pela Seção 4.1 do manual, o cliente "
                        "pode solicitar o cancelamento imediato ou exercer o direito de arrependimento em até 7 dias "
                        "corridos após receber o produto, com frete de devolução por conta da loja."
                    )
                }
            else:
                eligibility = {
                    "policy_guidance": (
                        f"Este pedido consta como '{status}'. Motivo registrado no sistema: "
                        f"'{ord_row['notes'] or 'Não especificado'}'."
                    )
                }

            results.append(
                {
                    "order_id": ord_row["order_id"],
                    "order_date": ord_row["order_date"],
                    "status": status,
                    "total_brl": ord_row["total_brl"],
                    "payment_method": ord_row["payment_method"],
                    "tracking_code": ord_row["tracking_code"],
                    "estimated_delivery": deliv_str,
                    "notes": ord_row["notes"],
                    "customer": {
                        "customer_id": cust["customer_id"],
                        "name": cust["name"],
                        "phone": cust["phone"],
                        "email": cust["email"],
                        "city": cust["city"],
                    }
                    if cust
                    else None,
                    "items": items,
                    "return_and_warranty_analysis": eligibility,
                }
            )

        return {"found": True, "orders_count": len(results), "orders": results}

    def simulate_payment_and_shipping(
        self,
        amount_brl: float,
        city: str = "Campo Grande",
        has_active_promotion: bool = False,
        is_large_instrument: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculate exact payment options (PIX, credit card installments, combined payment) and shipping rules.

        Args:
            amount_brl: Total purchase value in BRL.
            city: Destination city (e.g., 'Campo Grande', 'Dourados', 'São Paulo').
            has_active_promotion: True if the price already includes an active store promotion (disables 5% PIX discount).
            is_large_instrument: True for acoustic drum kits, digital pianos, or double basses (Section 5.2).
        """
        amount = float(amount_brl)
        installments = _compute_installments(amount)

        if has_active_promotion:
            pix_value = round(amount, 2)
            pix_explanation = (
                "R$ {:,.2f} à vista no PIX (item já está em promoção ativa; conforme Seção 6.2, "
                "o desconto de 5% do PIX não é cumulativo)."
            ).format(pix_value)
        else:
            pix_value = round(amount * 0.95, 2)
            pix_explanation = f"R$ {pix_value:,.2f} à vista no PIX (5% de desconto sobre R$ {amount:,.2f} - Seção 3)."

        city_norm = normalize_text(city)
        is_cg = "campo grande" in city_norm

        if is_cg:
            shipping = {
                "region": "Região Metropolitana de Campo Grande/MS (Seção 5.1)",
                "cost_brl": 0.0 if amount >= 500.0 else 35.0,
                "cost_description": "Frete GRÁTIS (pedido >= R$ 500,00)" if amount >= 500.0 else "Taxa fixa de R$ 35,00 (pedido < R$ 500,00)",
                "delivery_time": "1 a 3 dias úteis",
                "carrier": "Motoboy próprio da Empório da Música (contato telefônico prévio antes da entrega)",
            }
        else:
            shipping = {
                "region": f"Outras Cidades — {city} (Seção 5.2)",
                "cost_description": "Calculado automaticamente por CEP, peso e dimensões (todos os envios possuem seguro e rastreamento inclusos).",
                "modalities": [
                    {"service": "SEDEX (Correios)", "estimated_days": "2 a 5 dias úteis", "insurance_and_tracking": True},
                    {"service": "Jadlog (.package)", "estimated_days": "3 a 8 dias úteis", "insurance_and_tracking": True},
                    {"service": "PAC (Correios)", "estimated_days": "5 a 12 dias úteis", "insurance_and_tracking": True},
                ],
                "large_instrument_note": (
                    "ATENÇÃO: Instrumentos de grande porte (baterias acústicas, pianos digitais, contrabaixos) "
                    "podem exigir frete especial com cotação individual (Seção 5.2)."
                    if is_large_instrument
                    else None
                ),
            }

        return {
            "base_amount_brl": round(amount, 2),
            "pix_option": {"value_brl": pix_value, "details": pix_explanation},
            "debit_card_option": f"R$ {amount:,.2f} à vista (todas as bandeiras aceitas)",
            "boleto_option": f"R$ {amount:,.2f} à vista (compensação em até 3 dias úteis)",
            "credit_card_installments": installments,
            "shipping_info": shipping,
        }

    def consult_store_policy(self, topic: str) -> Dict[str, Any]:
        """
        Search the official Store Policy Manual (`políticas_da_loja.pdf`) by topic or question.

        Args:
            topic: Question or policy topic (e.g., 'horário', 'endereço', 'troca', 'devolução', 'garantia', 'frete', 'pagamento', 'lgpd', 'acessórios').
        """
        q_norm = normalize_text(topic)
        tokens = [t for t in q_norm.split() if len(t) > 2]

        scored_sections = []
        for sec in STORE_POLICY_SECTIONS:
            score = 0
            sec_text_norm = normalize_text(sec["title"] + " " + sec["content"] + " " + " ".join(sec["keywords"]))
            for kw in sec["keywords"]:
                if normalize_text(kw) in q_norm:
                    score += 3
            for tok in tokens:
                if tok in sec_text_norm:
                    score += 1
            if score > 0:
                scored_sections.append((score, sec))

        scored_sections.sort(key=lambda x: x[0], reverse=True)
        matched = [s[1] for s in scored_sections[:3]] if scored_sections else STORE_POLICY_SECTIONS[:4]

        return {
            "query": topic,
            "matched_sections_count": len(matched),
            "policies": matched,
        }