from __future__ import annotations

import argparse
import random
from datetime import date
from pathlib import Path

import pandas as pd
from faker import Faker


SEED = 20261027
N_FACT_ROWS = 50_000
UF_REGIAO = {
    "AC": "Norte", "AL": "Nordeste", "AP": "Norte", "AM": "Norte",
    "BA": "Nordeste", "CE": "Nordeste", "DF": "Centro-Oeste",
    "ES": "Sudeste", "GO": "Centro-Oeste", "MA": "Nordeste",
    "MT": "Centro-Oeste", "MS": "Centro-Oeste", "MG": "Sudeste",
    "PA": "Norte", "PB": "Nordeste", "PR": "Sul", "PE": "Nordeste",
    "PI": "Nordeste", "RJ": "Sudeste", "RN": "Nordeste", "RS": "Sul",
    "RO": "Norte", "RR": "Norte", "SC": "Sul", "SP": "Sudeste",
    "SE": "Nordeste", "TO": "Norte",
}
CIDADES = {
    "AC": ["Rio Branco", "Cruzeiro do Sul"], "AL": ["Maceió", "Arapiraca"],
    "AP": ["Macapá", "Santana"], "AM": ["Manaus", "Parintins"],
    "BA": ["Salvador", "Feira de Santana", "Vitória da Conquista"],
    "CE": ["Fortaleza", "Juazeiro do Norte"], "DF": ["Brasília"],
    "ES": ["Vitória", "Vila Velha"], "GO": ["Goiânia", "Anápolis"],
    "MA": ["São Luís", "Imperatriz"], "MT": ["Cuiabá", "Rondonópolis"],
    "MS": ["Campo Grande", "Dourados"], "MG": ["Belo Horizonte", "Uberlândia"],
    "PA": ["Belém", "Santarém"], "PB": ["João Pessoa", "Campina Grande"],
    "PR": ["Curitiba", "Londrina"], "PE": ["Recife", "Caruaru"],
    "PI": ["Teresina", "Parnaíba"], "RJ": ["Rio de Janeiro", "Niterói"],
    "RN": ["Natal", "Mossoró"], "RS": ["Porto Alegre", "Caxias do Sul"],
    "RO": ["Porto Velho", "Ji-Paraná"], "RR": ["Boa Vista"],
    "SC": ["Florianópolis", "Joinville"], "SP": ["São Paulo", "Campinas", "Santos"],
    "SE": ["Aracaju"], "TO": ["Palmas", "Araguaína"],
}
CATEGORIAS = {
    "Alimentos": ["Mercearia", "Congelados", "Bebidas"],
    "Higiene": ["Cuidados pessoais", "Higiene oral", "Perfumaria"],
    "Limpeza": ["Lavanderia", "Casa", "Desinfecção"],
    "Bazar": ["Utilidades", "Organização", "Descartáveis"],
    "Pet": ["Ração", "Acessórios", "Higiene pet"],
}
MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
           "sexta-feira", "sábado", "domingo"]
FERIADOS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2),
            (11, 15), (12, 25)}


def build_calendar() -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", "2026-12-31", freq="D")
    frame = pd.DataFrame({"data": dates})
    frame["ano"] = frame["data"].dt.year
    frame["trimestre"] = "T" + frame["data"].dt.quarter.astype(str)
    frame["mes"] = frame["data"].dt.month
    frame["nome_mes"] = frame["mes"].map(lambda value: MESES_PT[value - 1])
    frame["ano_mes"] = frame["data"].dt.strftime("%Y-%m")
    frame["ano_mes_num"] = frame["ano"] * 100 + frame["mes"]
    frame["dia"] = frame["data"].dt.day
    frame["dia_semana"] = frame["data"].dt.weekday.map(lambda value: DIAS_PT[value])
    frame["dia_semana_num"] = frame["data"].dt.weekday + 1
    frame["eh_fim_de_semana"] = frame["data"].dt.weekday >= 5
    frame["eh_dia_util"] = ~frame["eh_fim_de_semana"]
    frame["eh_feriado_fixo"] = frame["data"].map(
        lambda value: (value.month, value.day) in FERIADOS
    )
    return frame


def build_dimensions(fake: Faker) -> dict[str, pd.DataFrame]:
    regions = pd.DataFrame(
        [
            {"id_regiao": index, "uf": uf, "regiao": region}
            for index, (uf, region) in enumerate(sorted(UF_REGIAO.items()), start=1)
        ]
    )
    uf_to_region_id = dict(zip(regions["uf"], regions["id_regiao"], strict=True))

    product_rows = []
    brands = ["Serra Dourada", "Bom Vizinho", "Casa Viva", "Ponto Certo",
              "Vida Leve", "Brilho Real", "PetMais", "Vale Verde"]
    for product_id in range(1, 241):
        category = random.choice(list(CATEGORIAS))
        subcategory = random.choice(CATEGORIAS[category])
        product_rows.append({
            "id_produto": product_id,
            "nome_produto": f"{subcategory} {product_id:03d}",
            "categoria": category,
            "subcategoria": subcategory,
            "marca": random.choice(brands),
            "preco_lista": round(random.uniform(8, 820), 2),
            "custo_base": round(random.uniform(4, 620), 2),
        })
    products = pd.DataFrame(product_rows)

    seller_rows = []
    seller_performance = {}
    managers = ["Mariana Costa", "Rafael Nunes", "Patrícia Almeida", "Eduardo Lima"]
    for seller_id in range(1, 37):
        team = f"Equipe {(seller_id - 1) // 9 + 1}"
        seller_rows.append({
            "id_vendedor": seller_id,
            "nome_vendedor": fake.name(),
            "equipe": team,
            "gerente": managers[(seller_id - 1) // 9],
        })
        if seller_id in (1, 2, 3, 4):
            seller_performance[seller_id] = random.uniform(1.38, 1.68)
        elif seller_id in (35, 36, 34):
            seller_performance[seller_id] = random.uniform(0.52, 0.72)
        else:
            seller_performance[seller_id] = random.uniform(0.83, 1.23)
    sellers = pd.DataFrame(seller_rows)

    customer_rows = []
    segments = ["Pequeno varejo", "Supermercado", "Atacado", "Food service"]
    repeated_names = ["Mercado São José", "Comercial Oliveira", "Empório Central",
                      "Distribuidora União", "Mercadinho Bom Preço"]
    name_variants = ["Mercado Sao Jose", "Comercial de Oliveira", "Emporio Central",
                     "Distribuidora Uniao", "Mercadinho Bom Preco"]
    for customer_id in range(1, 6_001):
        uf = random.choice(list(UF_REGIAO))
        name = fake.company()
        if customer_id <= 30:
            base_index = (customer_id - 1) % len(repeated_names)
            name = repeated_names[base_index] if customer_id <= 15 else name_variants[base_index]
        customer_rows.append({
            "id_cliente": customer_id,
            "nome_cliente": name,
            "segmento": random.choices(segments, [0.42, 0.28, 0.18, 0.12])[0],
            "cidade": random.choice(CIDADES[uf]),
            "uf": uf,
            "id_regiao": uf_to_region_id[uf],
        })
    customers = pd.DataFrame(customer_rows)

    return {
        "dim_cliente": customers,
        "dim_produto": products,
        "dim_vendedor": sellers,
        "dim_regiao": regions,
        "dim_calendario": build_calendar(),
        "dim_etapa_cascata": pd.DataFrame({
            "id_etapa": [1, 2, 3, 4],
            "etapa": ["Faturamento", "Descontos", "Custos", "Lucro"],
            "ordem": [1, 2, 3, 4],
        }),
    }, seller_performance


def build_facts(dimensions: dict[str, pd.DataFrame],
                seller_performance: dict[int, float]) -> pd.DataFrame:
    customers = dimensions["dim_cliente"]
    products = dimensions["dim_produto"]
    product_ids = products["id_produto"].tolist()
    product_index = products.set_index("id_produto")
    customer_region = customers.set_index("id_cliente")["id_regiao"].to_dict()
    months = list(pd.period_range("2023-01", "2026-12", freq="M"))
    month_weights = [
        (1.55 if month.month in (11, 12) else
         0.88 if month.month in (1, 2) else 1.0) *
        (1 + 0.095 * (month.year - 2023))
        for month in months
    ]
    status_choices = ["Entregue", "Cancelado", "Devolvido"]
    status_weights = [0.935, 0.042, 0.023]
    channel_choices = ["Online", "Loja", "Representante"]
    channel_weights = [0.24, 0.19, 0.57]
    seller_ids = list(seller_performance)
    seller_weights = [seller_performance[seller_id] ** 1.5 for seller_id in seller_ids]

    rows = []
    item_id = 1
    order_id = 1
    while len(rows) < N_FACT_ROWS:
        chosen_period = random.choices(months, month_weights, k=1)[0]
        period_start = chosen_period.start_time.date()
        days_in_month = (chosen_period.end_time.date() - period_start).days + 1
        order_date = date(period_start.year, period_start.month,
                          random.randint(1, days_in_month))
        customer_id = random.randint(1, len(customers))
        seller_id = random.choices(seller_ids, seller_weights, k=1)[0]
        channel = random.choices(channel_choices, channel_weights, k=1)[0]
        products_in_order = random.sample(product_ids, random.randint(1, 4))
        for product_id in products_in_order:
            if len(rows) >= N_FACT_ROWS:
                break
            product = product_index.loc[product_id]
            quantity = random.choices([1, 2, 3, 4, 6, 12, 24], [0.26, 0.22, 0.18, 0.13, 0.10, 0.07, 0.04])[0]
            list_price = float(product["preco_lista"])
            cost = float(product["custo_base"])
            price = max(1.0, list_price * random.uniform(0.88, 1.12))
            cost = min(cost, price * random.uniform(0.55, 0.84))
            discount = min(0.28, max(0.0, random.betavariate(1.7, 8.0) * 0.48))
            status = random.choices(status_choices, status_weights, k=1)[0]
            performance = seller_performance[seller_id]
            if random.random() < min(0.55, max(0.04, (performance - 0.75) * 0.12)):
                discount = min(0.30, discount + random.uniform(0.01, 0.05))
            rows.append({
                "id_item_venda": item_id,
                "id_pedido": f"PED{order_id:07d}",
                "data": order_date.isoformat(),
                "id_cliente": customer_id,
                "id_produto": product_id,
                "id_vendedor": seller_id,
                "id_regiao": customer_region[customer_id],
                "quantidade": quantity,
                "preco_unitario": round(price, 2),
                "desconto_pct": round(discount, 4),
                "custo_unitario": round(cost, 2),
                "canal": channel,
                "status": status,
            })
            item_id += 1
        order_id += 1

    facts = pd.DataFrame(rows)
    # A small, intentional set of exact duplicate rows exercises key-based cleaning.
    duplicate_count = 75
    facts = pd.concat(
        [facts, facts.sample(duplicate_count, random_state=SEED)],
        ignore_index=True,
    ).astype(object)

    numeric_columns = [
        "id_item_venda", "id_cliente", "id_produto", "id_vendedor", "id_regiao",
        "quantidade", "preco_unitario", "desconto_pct", "custo_unitario",
    ]
    nd_count = max(1, int(N_FACT_ROWS * 0.007))
    for row_index, column in zip(
        random.sample(range(N_FACT_ROWS), nd_count),
        (random.choice(numeric_columns) for _ in range(nd_count)),
        strict=True,
    ):
        facts.at[row_index, column] = "ND"

    null_count = max(1, int(N_FACT_ROWS * 0.003))
    for row_index, column in zip(
        random.sample(range(N_FACT_ROWS), null_count),
        (random.choice(["quantidade", "preco_unitario", "custo_unitario"])
         for _ in range(null_count)),
        strict=True,
    ):
        facts.at[row_index, column] = None
    return facts


def build_targets(sellers: pd.DataFrame,
                  seller_performance: dict[int, float]) -> pd.DataFrame:
    rows = []
    target_id = 1
    for month in pd.period_range("2023-01", "2026-12", freq="M"):
        growth = 1 + (month.year - 2023) * 0.095
        seasonality = 1.30 if month.month in (11, 12) else 0.92 if month.month == 1 else 1
        for seller_id in sellers["id_vendedor"]:
            base = random.uniform(47_000, 65_000)
            # High- and low-performing sellers are intentionally both present.
            target = base * growth * seasonality * (1 + (seller_performance[seller_id] - 1) * 0.12)
            rows.append({
                "id_meta": target_id,
                "id_vendedor": seller_id,
                "data_mes": month.start_time.date().isoformat(),
                "ano_mes_num": month.year * 100 + month.month,
                "valor_meta": round(target, 2),
            })
            target_id += 1
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera dados sintéticos de vendas.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "dados" / "brutos",
        help="Pasta para os CSVs brutos (padrão: ../dados/brutos).",
    )
    args = parser.parse_args()

    random.seed(SEED)
    fake = Faker("pt_BR")
    Faker.seed(SEED)
    dimensions, seller_performance = build_dimensions(fake)
    facts = build_facts(dimensions, seller_performance)
    targets = build_targets(dimensions["dim_vendedor"], seller_performance)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name, frame in dimensions.items():
        frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8")
    facts.to_csv(args.output_dir / "fato_vendas.csv", index=False, encoding="utf-8")
    targets.to_csv(args.output_dir / "meta_mensal.csv", index=False, encoding="utf-8")
    print(f"Dados brutos gravados em {args.output_dir}")
    print(f"Fato: {len(facts):,} linhas; período: 2023-2026; seed: {SEED}")


if __name__ == "__main__":
    main()
