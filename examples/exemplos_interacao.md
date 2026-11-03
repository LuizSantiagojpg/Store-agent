# Exemplos de Interação com o Agente — Empório da Música

Abaixo estão **5 conversas completas (multi-turn)** demonstrando o comportamento do agente **Tom (Empório da Música)**, incluindo o rastreamento das **ferramentas determinísticas (`Tool Calls`)** acionadas em tempo real sobre as tabelas operacionais (`data/*.csv`) e o Manual de Políticas (`data/políticas_da_loja.pdf`).

---

## Conversa 1: Consulta de Catálogo com Filtro de Estoque e Status (Situação Não-Trivial de Dados)

**Cenário:** O cliente pede opções de violões até R$ 1.000,00. Na tabela `products.csv`, existem 14 violões nessa faixa de preço, sendo **12 disponíveis para pronta entrega** e **2 que não podem ser vendidos** (`Giannini GF-3D` está com `stock_quantity = 0` e `Shelby SN-7C` está com `status = "discontinued"`). Além disso, no segundo turno o cliente pede um encordoamento e um afinador avulso (fora de escopo conforme Seções 1 e 7.1).

### Turno 1
👤 **Cliente:**
> Quais opções de violões disponíveis custando até R$1000?

🔧 **Tool Call Executada:**
```json
{
  "tool": "search_products",
  "args": {
    "category": "Violões",
    "max_price": 1000.0
  }
}
```

🎸 **Tom (Empório da Música):**
> Fala! Tudo bem? Consultei nosso sistema agora mesmo e temos **12 modelos de violões disponíveis para pronta entrega** custando até R$ 1.000,00. Separei por estilo para facilitar sua escolha:
>
> **Violões Clássicos (Cordas de Nylon — Acústicos):**
> 1. **Tagima Memphis AC-39 Nylon Natural** (`ID 83`) — **R$ 429,90** (ou **R$ 408,41 no PIX** com 5% OFF | até 5x sem juros de R$ 85,98) · *15 un. em estoque*
> 2. **Rozini RC-104 Nylon Estudante** (`ID 85`) — **R$ 459,90** (ou **R$ 436,91 no PIX** | até 5x sem juros de R$ 91,98) · *10 un. em estoque*
> 3. **Yamaha C40 Nylon Natural** (`ID 81`) — **R$ 599,90** (ou **R$ 569,91 no PIX** | até 6x sem juros de R$ 99,98) · *12 un. em estoque*
> 4. **Giannini GN-15 Nylon Cedro Natural** (`ID 84`) — **R$ 689,00** (ou **R$ 654,55 no PIX** | até 6x sem juros de R$ 114,83) · *6 un. em estoque*
> 5. **Yamaha C70 Nylon Natural** (`ID 82` — tampo sólido em Spruce) — **R$ 849,00** (ou **R$ 806,55 no PIX** | até 8x sem juros de R$ 106,12) · *8 un. em estoque*
>
> **Violões Folk / Dreadnought (Cordas de Aço):**
> 6. **Shelby SN-100 Folk Aço Preto** (`ID 89`) — **R$ 549,00** (ou **R$ 521,55 no PIX** | até 6x sem juros de R$ 91,50) · *5 un. em estoque*
> 7. **Giannini GF-1R Aço Folk Sunburst** (`ID 88`) — **R$ 579,90** (ou **R$ 550,91 no PIX** | até 6x sem juros de R$ 96,65) · *7 un. em estoque*
> 8. **Yamaha F310 Aço Natural** (`ID 87`) — **R$ 699,90** (ou **R$ 664,91 no PIX** | até 6x sem juros de R$ 116,65) · *14 un. em estoque*
> 9. **Tagima Dallas Tuner Aço Natural** (`ID 86` — com afinador embutido) — **R$ 749,00** (ou **R$ 711,55 no PIX** | até 7x sem juros de R$ 107,00) · *9 un. em estoque*
> 10. **Shelby SGD-195E Elétrico Aço Sunburst** (`ID 107` — eletroacústico com captação) — **R$ 799,00** (ou **R$ 759,05 no PIX** | até 7x sem juros de R$ 114,14) · *6 un. em estoque*
> 11. **Tagima Woodstock Dreadnought Natural** (`ID 91`) — **R$ 899,00** (ou **R$ 854,05 no PIX** | até 8x sem juros de R$ 112,38) · *11 un. em estoque*
>
> **Violão 7 Cordas:**
> 12. **Tagima TW-7 7 Cordas Aço Natural** (`ID 112`) — **R$ 999,00** (ou **R$ 949,05 no PIX** | até 9x sem juros de R$ 111,00) · *6 un. em estoque*
>
> *(Nota de transparência: o **Giannini GF-3D Dreadnought Sunburst** de R$ 799,90 está temporariamente esgotado no estoque, e o **Shelby SN-7C 7 Cordas Nylon** de R$ 749,00 foi descontinuado — por isso o **Tagima Woodstock** e o **Tagima TW-7** são as melhores alternativas imediatas!)*
>
> Você prefere cordas de **nylon** (mais macias para começar) ou de **aço** (som mais brilhante e encorpado)?

### Turno 2
👤 **Cliente:**
> Gostei do Yamaha F310! Aproveitando, vocês têm jogo de cordas extra, palhetas e capa (bag) pra eu levar junto?

🔧 **Tool Call Executada:**
```json
{
  "tool": "search_products",
  "args": {
    "query": "cordas palhetas capa bag"
  }
}
```

🎸 **Tom (Empório da Música):**
> Excelente escolha, o **Yamaha F310** (R$ 699,90 ou **R$ 664,91 no PIX**) é um tanque de guerra e tem um som lindo! Como ele passa de R$ 500,00, se você estiver na Região Metropolitana de Campo Grande o **frete sai GRÁTIS** (entregamos em 1 a 3 dias úteis pelo nosso motoboy).
>
> Sobre os itens extras: aqui na **Empório da Música** nós trabalhamos **exclusivamente com instrumentos musicais** — não comercializamos acessórios avulsos como encordoamentos, palhetas, cabos, capas/cases, pedais ou amplificadores. Para esses acessórios, recomendamos procurar lojas parceiras especializadas em peças e acessórios musicais aqui da região! Quer que eu simule as parcelas do seu Yamaha F310?

---

## Conversa 2: Consulta de Preço, Promoção Expirada vs. Promoção Ativa e Regra de Não-Cumulatividade do PIX

**Cenário:** O cliente pergunta o preço do **Takamine GD20** (`product_id=95`), que possui uma promoção de 12% na tabela `promotions.csv`, mas com `is_active = 0` (expirada). Em seguida, pergunta quais violões estão em promoção ativa hoje e se pode somar os 5% do PIX.

### Turno 1
👤 **Cliente:**
> Quanto custa o Takamine GD20? Vi um anúncio antigo de 12% de desconto nele, ainda está valendo?

🔧 **Tool Call Executada:**
```json
{
  "tool": "get_product_details",
  "args": {
    "product_name_or_id": "Takamine GD20"
  }
}
```

🎸 **Tom (Empório da Música):**
> Olá! Consultei a ficha do **Takamine GD20 Dreadnought Natural** (`ID 95` — tampo sólido em Cedro) agora mesmo no nosso sistema:
>
> - **Status da Promoção:** A campanha anterior de **12% OFF (*Oferta Especial*) já está encerrada** no sistema (`inativa`). Seguindo nossa política de transparência, informamos sempre o valor vigente atualizado.
> - **Estoque Atual:** **5 unidades** disponíveis para pronta entrega.
> - **Preço de Tabela Vigente:** **R$ 2.199,00**
> - **Preço à vista no PIX (5% de desconto):** **R$ 2.089,05** (economia de R$ 109,95!)
> - **Parcelamento no Cartão de Crédito:** em **até 12x sem juros de R$ 183,25** (ou você pode combinar PIX + Cartão de Crédito, pois a compra é acima de R$ 2.000,00!).
> - **Frete:** **GRÁTIS** para toda a Região Metropolitana de Campo Grande (1 a 3 dias úteis).

### Turno 2
👤 **Cliente:**
> Entendi! E tem algum violão de aço com tampo sólido que esteja com promoção ativa hoje? Se tiver, consigo mais 5% pagando no PIX?

🔧 **Tool Call Executada:**
```json
{
  "tool": "search_products",
  "args": {
    "category": "Violões",
    "only_active_promotions": true
  }
}
```

🎸 **Tom (Empório da Música):**
> Temos sim! Hoje temos **2 violões de aço com tampo sólido em promoção ativa** no catálogo ( inclusive um na mesma faixa do Takamine GD20!):
>
> 1. **Crafter HT-100 Folk Aço Natural** (`ID 90` — Tampo sólido em Spruce Engelmann, 3 un. em estoque):
>    - **Preço Original:** ~~R$ 2.399,00~~
>    - **Desconto Ativo:** **18% OFF** (*Desconto Exclusivo*)
>    - **Preço Promocional:** **R$ 1.967,18** (ou em até **12x sem juros de R$ 163,93**)
> 2. **Taylor 110e Dreadnought Natural** (`ID 94` — Tampo sólido em Sitka Spruce + captação ES2, 4 un. em estoque):
>    - **Preço Original:** ~~R$ 5.999,00~~
>    - **Desconto Ativo:** **8% OFF** (*Desconto Exclusivo*)
>    - **Preço Promocional:** **R$ 5.519,08** (ou em até **12x sem juros de R$ 459,92**)
>
> **Importante sobre o PIX (Seção 6.2 da nossa política):** As promoções da loja **não são cumulativas**. Por isso, nos itens que já estão com desconto promocional ativo (como os 18% do Crafter HT-100 ou os 8% do Taylor 110e), o desconto adicional de 5% do PIX não se aplica — você já garante o valor promocional de **R$ 1.967,18** tanto no PIX quanto parcelado em até 12x sem juros!

---

## Conversa 3: Situação Não-Trivial — Cruzamento em Tempo Real de Pedidos + Políticas de Devolução e Arrependimento

**Cenário:** O cliente pergunta genericamente *"Me arrependi da minha compra, posso devolver meu pedido?"* e depois informa dois pedidos reais do sistema (`Pedido #8` de Ana Carolina Ferreira e `Pedido #4` de Lucas Mendes da Silva) para verificar se cada um pode ser devolvido.

### Turno 1
👤 **Cliente:**
> Me arrependi da minha compra, posso devolver meu pedido?

🔧 **Tool Call Executada:**
```json
{
  "tool": "consult_store_policy",
  "args": {
    "topic": "direito de arrependimento devolução troca prazos"
  }
}
```

🎸 **Tom (Empório da Música):**
> Olá! Pode sim, desde que esteja dentro das condições da nossa **Política de Trocas e Devoluções (Seção 4 do Manual / Código de Defesa do Consumidor)**:
>
> - **Prazo para Direito de Arrependimento (Compras Online — Seção 4.1):** Você tem até **7 (sete) dias corridos após o recebimento do produto** para solicitar a devolução, sem precisar dar justificativa.
> - **Condições do Produto:** O instrumento deve estar na **embalagem original, sem sinais de uso**, acompanhado de todos os manuais e itens originais.
> - **Frete e Reembolso:** No caso de arrependimento dentro do prazo, o **frete de devolução é 100% por conta da Empório da Música**, e o reembolso é feito na mesma forma de pagamento original em **até 10 dias úteis**.
> - **Exceções (Seção 4.4):** Instrumentos com personalização/setup sob encomenda, itens de liquidação marcados como *"venda final"* e boquilhas de sopro (por higiene) não são elegíveis.
>
> Me passa por favor o **número do seu pedido** ou o seu **nome/e-mail** para eu consultar a data de entrega aqui no sistema agora mesmo!

### Turno 2
👤 **Cliente:**
> Verifica pra mim dois pedidos: o pedido #8 da minha esposa Ana Carolina Ferreira e o meu pedido antigo #4 (Lucas Mendes). Hoje é dia 02/03/2026.

🔧 **Tool Calls Executadas:**
```json
[
  {
    "tool": "lookup_customer_orders",
    "args": {
      "order_id": 8,
      "reference_date": "2026-03-02"
    }
  },
  {
    "tool": "lookup_customer_orders",
    "args": {
      "order_id": 4,
      "reference_date": "2026-03-02"
    }
  }
]
```

🎸 **Tom (Empório da Música):**
> Consultei os dois pedidos aqui no sistema considerando a data de hoje (**02/03/2026**). Veja a situação exata de cada um:
>
> ### 1. Pedido `#8` — Ana Carolina Ferreira (`Ukulele Concert Kala KA-C Mogno` — R$ 349,90)
> - **Data do Pedido:** 15/02/2026 | **Entrega Estimada/Recebimento:** 28/02/2026 (`Rastreio: BRJL5544332BR`)
> - **Status para Devolução por Arrependimento:** ✅ **ELEGÍVEL!**
> - **Por quê:** Como a entrega ocorreu em **28/02/2026**, hoje (**02/03/2026**) faz apenas **2 dias corridos** desde o recebimento (o prazo de 7 dias corridos vai até **07/03/2026**).
> - **Como proceder:** Basta manter o Ukulele Kala KA-C sem sinais de uso na embalagem original. Nós geramos a coleta/postagem reversa sem custo de frete para vocês e estornamos os **R$ 349,90** no cartão de débito em até 10 dias úteis!
>
> ### 2. Pedido `#4` — Lucas Mendes da Silva (`Violão Giannini GF-3D Dreadnought Sunburst` — R$ 799,90)
> - **Data do Pedido:** 10/12/2025 | **Data da Entrega:** 22/12/2025 (`Rastreio: BRQM7890123BR`)
> - **Status para Devolução por Arrependimento ou Preferência:** ❌ **FORA DO PRAZO.**
> - **Por quê:** Já se passaram **70 dias corridos** desde a entrega em 22/12/2025 (o prazo de 7 dias de arrependimento encerrou em **29/12/2025**, e o prazo de 30 dias para troca direta na loja por defeito encerrou em **09/01/2026**).
> - **Observação importante sobre Garantia:** Caso o seu Giannini GF-3D tenha apresentado algum **defeito de fabricação**, você ainda está coberto pela **Garantia Legal de 90 dias (CDC — Seção 8.1)** até **22/03/2026**, além da garantia de fábrica da Giannini, e nós podemos intermediar o acionamento para você!

---

## Conversa 4: Informações Gerais da Loja, Frete para o Interior do MS e Pedido Cancelado

**Cenário:** O cliente pergunta o endereço e horários de funcionamento da loja e aproveita para checar o que aconteceu com o pedido `#19` (de Pedro Henrique Oliveira) que consta como cancelado.

### Turno 1
👤 **Cliente:**
> Qual o endereço da loja e o horário de funcionamento? Quero saber também por que o meu pedido #19 foi cancelado.

🔧 **Tool Calls Executadas:**
```json
[
  {
    "tool": "consult_store_policy",
    "args": {
      "topic": "endereço localização horário de funcionamento telefone whatsapp"
    }
  },
  {
    "tool": "lookup_customer_orders",
    "args": {
      "order_id": 19
    }
  }
]
```

🎸 **Tom (Empório da Música):**
> Olá, Pedro! Tudo bem? Aqui estão os dados da nossa loja física e a verificação do seu pedido `#19`:
>
> ### 📍 Endereço e Canais de Contato (Seção 1.2 e 7)
> - **Endereço:** Rua 14 de Maio, 3200 — Centro, Campo Grande/MS — CEP 79202-333
> - **Horário de Funcionamento (Loja Física e WhatsApp):**
>   - **Segunda a Sexta-feira:** 09:00 às 18:00
>   - **Sábado:** 09:00 às 13:00
>   - **Domingos e Feriados:** Fechado
> - **Telefones:** (67) 3341-4444 (Fixo/Geral) | **(67) 3321-4500** (WhatsApp Oficial de Atendimento)
> - **E-mail:** contato@emporiodamusica.com.br
>
> ---
> ### 📦 Situação do Pedido `#19` (`Taylor 214ce Elétrico Aço Natural` — R$ 7.499,00)
> - **Data do Pedido:** 22/02/2026 | **Forma de Pagamento:** Boleto Bancário
> - **Status:** `Cancelado`
> - **Motivo registrado no sistema:** *"Pagamento não confirmado dentro do prazo"* (o boleto tem prazo de compensação de até 3 dias úteis e acabou vencendo sem baixa bancária).
>
> A boa notícia é que ainda temos **2 unidades em estoque** do **Taylor 214ce Elétrico Aço Natural** (`ID 106` — R$ 7.499,00)! Se quiser refazer o pedido hoje, no **PIX à vista ele sai por R$ 7.124,05** (5% de desconto, economizando R$ 374,95), ou em **até 12x sem juros de R$ 624,92**, ou ainda combinando PIX + Cartão!

---

## Conversa 5: Transparência sobre Divergência de Cadastro (Data Quality Guardrail) e Categorias Sem Estoque

**Cenário:** O cliente pergunta sobre saxofones/violinos (categorias 6, 7 e 8 que não têm produtos em `products.csv`) e sobre o contrabaixo `Music Man Bass 1X` (`product_id=135`), onde o CSV da loja possui uma inconsistência entre o título (*Music Man*) e a descrição (*Fender Jazz Bass*).

### Turno 1
👤 **Cliente:**
> Vocês têm saxofone alto em estoque? E me passa também os detalhes do baixo Music Man Bass 1X (ID 135).

🔧 **Tool Calls Executadas:**
```json
[
  {
    "tool": "search_products",
    "args": {
      "query": "saxofone"
    }
  },
  {
    "tool": "get_product_details",
    "args": {
      "product_name_or_id": "135"
    }
  }
]
```

🎸 **Tom (Empório da Música):**
> Vamos lá! Consultei os dois itens para você com total transparência:
>
> 1. **Sobre o Saxofone Alto (Instrumentos de Sopro):**
>    - Embora a Empório da Música trabalhe com as categorias de *Instrumentos de Sopro (Madeiras e Metais)* e *Cordas Orquestrais*, **no momento estamos sem nenhum modelo cadastrado disponível em estoque** nessas categorias no sistema.
>
> 2. **Sobre o Contrabaixo `ID 135` (`Music Man Bass 1X Electric Bass`):**
>    - **Preço de Tabela:** **R$ 8.732,00** (ou **R$ 8.295,40 à vista no PIX** com 5% de desconto | até **12x sem juros de R$ 727,67** no cartão)
>    - **Estoque:** 9 unidades ativas.
>    - ⚠️ **Aviso de Transparência Técnica:** Identificamos uma divergência cadastral na ficha desse item no nosso sistema — o título está registrado como *"Music Man Bass 1X"* com corpo em *Ash* (cor *Red*, 4 cordas), mas o texto descritivo menciona *"Fender Jazz Bass com corpo em Alder"*. Antes de você fechar o pedido, posso solicitar a confirmação visual no nosso estoque físico na Rua 14 de Maio para garantir exatamente o modelo e especificações antes do envio!
