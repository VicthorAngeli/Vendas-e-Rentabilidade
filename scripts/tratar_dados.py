from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TABLES = [
    "fato_vendas", "dim_cliente", "dim_produto", "dim_vendedor",
    "dim_regiao", "dim_calendario", "meta_mensal", "dim_etapa_cascata",
]
INTEGER_COLUMNS = {
    "fato_vendas": ["id_item_venda", "id_cliente", "id_produto", "id_vendedor",
                    "id_regiao", "quantidade"],
    "dim_cliente": ["id_cliente", "id_regiao"],
    "dim_produto": ["id_produto"],
    "dim_vendedor": ["id_vendedor"],
    "dim_regiao": ["id_regiao"],
    "dim_calendario": ["ano", "mes", "ano_mes_num", "dia", "dia_semana_num"],
    "meta_mensal": ["id_meta", "id_vendedor", "ano_mes_num"],
    "dim_etapa_cascata": ["id_etapa", "ordem"],
}
FLOAT_COLUMNS = {
    "fato_vendas": ["preco_unitario", "desconto_pct", "custo_unitario"],
    "dim_produto": ["preco_lista", "custo_base"],
    "meta_mensal": ["valor_meta"],
}
DATE_COLUMNS = {
    "fato_vendas": ["data"],
    "dim_calendario": ["data"],
    "meta_mensal": ["data_mes"],
}
KEY_COLUMNS = {
    "fato_vendas": ["id_item_venda"],
    "dim_cliente": ["id_cliente"],
    "dim_produto": ["id_produto"],
    "dim_vendedor": ["id_vendedor"],
    "dim_regiao": ["id_regiao"],
    "dim_calendario": ["data"],
    "meta_mensal": ["id_meta"],
    "dim_etapa_cascata": ["id_etapa"],
}


def read_raw(raw_dir: Path, table: str) -> pd.DataFrame:
    path = raw_dir / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(f"CSV bruto não encontrado: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def normalize_frame(table: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    nd_count = int(
        frame.astype("string").apply(
            lambda column: column.str.strip().str.upper().eq("ND")
        ).sum().sum()
    )
    report = {
        "tabela": table,
        "linhas_entrada": int(len(frame)),
        "duplicatas_por_chave_removidas": 0,
        "linhas_removidas_por_chave_obrigatoria": 0,
        "valores_nd_convertidos": 0,
        "nulos_numericos_imputados": 0,
        "nulos_textuais_corrigidos": 0,
    }
    frame = frame.replace(r"^\s*ND\s*$", pd.NA, regex=True)
    frame = frame.replace(r"^\s*$", pd.NA, regex=True)
    report["valores_nd_convertidos"] = nd_count

    for column in INTEGER_COLUMNS.get(table, []):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in FLOAT_COLUMNS.get(table, []):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in DATE_COLUMNS.get(table, []):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime("%Y-%m-%d")
        frame[column] = frame[column].replace("NaT", pd.NA)

    before = len(frame)
    frame = frame.drop_duplicates(subset=KEY_COLUMNS[table], keep="first")
    report["duplicatas_por_chave_removidas"] = int(before - len(frame))

    required_keys = KEY_COLUMNS[table]
    if table == "fato_vendas":
        required_keys = [
            "id_item_venda", "id_pedido", "data", "id_cliente", "id_produto",
            "id_vendedor", "id_regiao",
        ]
    if table == "meta_mensal":
        required_keys = ["id_meta", "id_vendedor", "data_mes"]
    before = len(frame)
    frame = frame.dropna(subset=required_keys).copy()
    report["linhas_removidas_por_chave_obrigatoria"] = int(before - len(frame))

    for column in INTEGER_COLUMNS.get(table, []):
        if frame[column].isna().any():
            if column.startswith("id_") or column in ("ano", "mes", "dia", "ano_mes_num"):
                if column not in required_keys:
                    frame[column] = frame[column].fillna(frame[column].median())
            else:
                frame[column] = frame[column].fillna(frame[column].median())
        frame[column] = frame[column].round().astype("int64")
    for column in FLOAT_COLUMNS.get(table, []):
        missing = int(frame[column].isna().sum())
        if missing:
            frame[column] = frame[column].fillna(frame[column].median())
            report["nulos_numericos_imputados"] += missing
        frame[column] = frame[column].astype("float64").round(4)
    for column in frame.select_dtypes(include="object").columns:
        frame[column] = frame[column].astype("string").str.strip()
        if column not in required_keys and column not in DATE_COLUMNS.get(table, []):
            missing = int(frame[column].isna().sum())
            if missing:
                frame[column] = frame[column].fillna("Não informado")
                report["nulos_textuais_corrigidos"] += missing
    for column in ("eh_fim_de_semana", "eh_dia_util", "eh_feriado_fixo"):
        if column in frame.columns:
            frame[column] = frame[column].astype("string").str.lower().map(
                {"true": True, "false": False, "1": True, "0": False}
            ).fillna(False)

    report["linhas_saida"] = int(len(frame))
    report["valores_corrigidos"] = (
        report["valores_nd_convertidos"] + report["nulos_numericos_imputados"]
        + report["nulos_textuais_corrigidos"]
    )
    return frame, report


def clean_facts(facts: pd.DataFrame, dimensions: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    table = "fato_vendas"
    nd_count = int(
        facts.astype("string").apply(
            lambda column: column.str.strip().str.upper().eq("ND")
        ).sum().sum()
    )
    report = {
        "tabela": table,
        "linhas_entrada": int(len(facts)),
        "duplicatas_por_chave_removidas": 0,
        "linhas_removidas_por_chave_obrigatoria": 0,
        "valores_nd_convertidos": 0,
        "nulos_numericos_imputados": 0,
        "nulos_textuais_corrigidos": 0,
    }
    facts = facts.replace(r"^\s*ND\s*$", pd.NA, regex=True)
    facts = facts.replace(r"^\s*$", pd.NA, regex=True)
    report["valores_nd_convertidos"] = nd_count
    for column in INTEGER_COLUMNS[table]:
        facts[column] = pd.to_numeric(facts[column], errors="coerce")
    for column in FLOAT_COLUMNS[table]:
        facts[column] = pd.to_numeric(facts[column], errors="coerce")
    facts["data"] = pd.to_datetime(facts["data"], errors="coerce")

    before = len(facts)
    facts = facts.drop_duplicates(subset=["id_item_venda"], keep="first")
    report["duplicatas_por_chave_removidas"] = int(before - len(facts))

    valid_values = {
        "id_cliente": set(dimensions["dim_cliente"]["id_cliente"]),
        "id_produto": set(dimensions["dim_produto"]["id_produto"]),
        "id_vendedor": set(dimensions["dim_vendedor"]["id_vendedor"]),
        "id_regiao": set(dimensions["dim_regiao"]["id_regiao"]),
    }
    required = ["id_item_venda", "id_pedido", "data", *valid_values]
    valid = facts[required].notna().all(axis=1)
    for column, values in valid_values.items():
        valid &= facts[column].isin(values)
    before = len(facts)
    facts = facts.loc[valid].copy()
    report["linhas_removidas_por_chave_obrigatoria"] = int(before - len(facts))

    for column in INTEGER_COLUMNS[table]:
        if facts[column].isna().any():
            if column in ("id_item_venda", "id_cliente", "id_produto",
                          "id_vendedor", "id_regiao"):
                raise ValueError(f"Chave numérica nula após validação: {column}")
            missing = int(facts[column].isna().sum())
            facts[column] = facts[column].fillna(facts[column].median())
            report["nulos_numericos_imputados"] += missing
        facts[column] = facts[column].round().astype("int64")
    for column in FLOAT_COLUMNS[table]:
        missing = int(facts[column].isna().sum())
        if missing:
            median = facts[column].median()
            facts[column] = facts[column].fillna(median)
            report["nulos_numericos_imputados"] += missing
        facts[column] = facts[column].astype("float64").round(4)
    facts["data"] = facts["data"].dt.strftime("%Y-%m-%d")
    for column in ("id_pedido", "canal", "status"):
        missing = int(facts[column].isna().sum())
        if missing:
            facts[column] = facts[column].fillna("Não informado")
            report["nulos_textuais_corrigidos"] += missing
        facts[column] = facts[column].astype("string").str.strip()
    report["linhas_saida"] = int(len(facts))
    report["valores_corrigidos"] = (
        report["valores_nd_convertidos"] + report["nulos_numericos_imputados"]
        + report["nulos_textuais_corrigidos"]
    )
    return facts, report


def clean_dimensions(raw_dir: Path) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    dimensions: dict[str, pd.DataFrame] = {}
    reports = []
    for table in TABLES:
        if table in ("fato_vendas", "meta_mensal"):
            continue
        frame, report = normalize_frame(table, read_raw(raw_dir, table))
        dimensions[table] = frame
        reports.append(report)

    targets, report = normalize_frame("meta_mensal", read_raw(raw_dir, "meta_mensal"))
    valid_sellers = set(dimensions["dim_vendedor"]["id_vendedor"])
    before = len(targets)
    targets = targets.loc[targets["id_vendedor"].isin(valid_sellers)].copy()
    report["linhas_removidas_por_chave_obrigatoria"] += int(before - len(targets))
    report["linhas_saida"] = int(len(targets))
    dimensions["meta_mensal"] = targets
    reports.append(report)

    expected_tables = {
        "dim_cliente": "id_cliente",
        "dim_produto": "id_produto",
        "dim_vendedor": "id_vendedor",
        "dim_regiao": "id_regiao",
    }
    for table, key in expected_tables.items():
        if dimensions[table][key].duplicated().any():
            raise ValueError(f"Chave duplicada após limpeza: {table}.{key}")
    return dimensions, reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Limpa e valida os CSVs sintéticos.")
    parser.add_argument("--input-dir", type=Path, default=ROOT / "dados" / "brutos")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dados")
    args = parser.parse_args()

    dimensions, reports = clean_dimensions(args.input_dir)
    facts, fact_report = clean_facts(
        read_raw(args.input_dir, "fato_vendas"), dimensions
    )
    reports.append(fact_report)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in dimensions.items():
        frame.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8")
    facts.to_csv(args.output_dir / "fato_vendas.csv", index=False, encoding="utf-8")
    quality = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "metodo_deduplicacao": "chave primária (nunca nome_cliente)",
        "tabelas": reports,
        "observacoes": [
            "ND e vazios em colunas numéricas são convertidos em nulos.",
            "Valores numéricos não-chave ausentes são imputados pela mediana da coluna.",
            "Linhas de fato com data/chaves ausentes ou referências inválidas são removidas.",
            "Nomes semelhantes permanecem quando possuem chaves de cliente distintas.",
        ],
    }
    (args.output_dir / "relatorio_qualidade.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(quality, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
