from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "VendasRentabilidade.Report"
MODEL_DIR = ROOT / "VendasRentabilidade.SemanticModel"
DEFINITION_DIR = REPORT_DIR / "definition"
TABLE_DIR = MODEL_DIR / "definition" / "tables"
DATA_DIR = ROOT / "dados"
DEFAULT_POWER_QUERY_DATA_PATH = r"C:\PowerBI\VendasRentabilidade\dados"

SCHEMAS = {
    "pbip": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
    "pbir": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
    "report": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
    "page": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
    "pages": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
    "version": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
    "visual": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.13.0/schema.json",
    "semantic_model": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
}

MONEY_FORMAT = 'R$ #,##0.00; (R$ #,##0.00); R$ 0.00'
PERCENT_FORMAT = '0.0%;-0.0%;0.0%'


def new_guid() -> str:
    return str(uuid.uuid4())


def tmdl_quote(name: str) -> str:
    return f"'{name}'" if re.search(r"[^A-Za-z0-9_]", name) else name


def m_text(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

def pbi_text_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def pbi_literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def read_column_types(table: str) -> list[tuple[str, str]]:
    frame = pd.read_csv(DATA_DIR / f"{table}.csv", nrows=0, encoding="utf-8")
    if table == "dim_calendario":
        bool_columns = {"eh_fim_de_semana", "eh_dia_util", "eh_feriado_fixo"}
    else:
        bool_columns = set()
    int_columns = {
        "id_item_venda", "id_cliente", "id_produto", "id_vendedor",
        "id_regiao", "id_meta", "id_etapa", "id_cascata", "quantidade", "ano",
        "mes", "ano_mes_num", "dia", "dia_semana_num", "ordem",
    }
    float_columns = {
        "preco_unitario", "desconto_pct", "custo_unitario", "preco_lista",
        "custo_base", "valor_meta",
    }
    date_columns = {"data", "data_mes"}
    result = []
    for column in frame.columns:
        if column in int_columns:
            data_type = "int64"
        elif column in float_columns:
            data_type = "double"
        elif column in date_columns:
            data_type = "dateTime"
        elif column in bool_columns:
            data_type = "boolean"
        else:
            data_type = "string"
        result.append((column, data_type))
    return result


def m_transform_type(column: str, data_type: str) -> str:
    mapping = {
        "int64": "Int64.Type",
        "double": "type number",
        "dateTime": "type date",
        "boolean": "type logical",
        "string": "type text",
    }
    return f"{{{m_text(column)}, {mapping[data_type]}}}"


def build_partition(table: str, columns: list[tuple[str, str]]) -> str:
    column_types = ", ".join(m_transform_type(name, data_type) for name, data_type in columns)
    m_expr = (
        "let\n"
        f"    Source = Csv.Document(File.Contents(PastaDados & \"\\{table}.csv\"), "
        "[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
        "    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
        f"    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {{{column_types}}}, \"en-US\")\n"
        "in\n"
        "    ChangedTypes"
    )
    indented = "\n".join(f"            {line}" for line in m_expr.splitlines())
    return (
        f"    partition {tmdl_quote(table)} = m\n"
        "        mode: import\n"
        "        source =\n"
        f"{indented}\n"
    )


def column_tmdl(table: str, columns: list[tuple[str, str]]) -> list[str]:
    lines: list[str] = []
    hidden = {
        "id_item_venda", "id_cliente", "id_produto", "id_vendedor", "id_regiao",
        "id_meta", "id_etapa", "ano_mes_num", "dia_semana_num", "ordem",
    }
    for name, data_type in columns:
        lines.extend([
            f"    column {tmdl_quote(name)}",
            f"        dataType: {data_type}",
            "        isHidden" if name in hidden else "        summarizeBy: none",
            f"        sourceColumn: {tmdl_quote(name)}",
            f"        lineageTag: {new_guid()}",
        ])
        if name in {"preco_unitario", "preco_lista", "custo_unitario", "custo_base", "valor_meta"}:
            lines.append(f"        formatString: {MONEY_FORMAT}")
        if name == "desconto_pct":
            lines.append(f"        formatString: {PERCENT_FORMAT}")
        if table == "dim_etapa_cascata" and name == "etapa":
            lines.append("        sortByColumn: ordem")
        if table == "dim_calendario" and name == "nome_mes":
            lines.append("        sortByColumn: mes")
    return lines


MEASURES = [
    ("Faturamento", "Faturamento", "SUMX(FILTER(fato_vendas, fato_vendas[status] = \"Entregue\"), fato_vendas[quantidade] * fato_vendas[preco_unitario] * (1 - fato_vendas[desconto_pct]))", MONEY_FORMAT, "Receita líquida dos itens entregues, após descontos."),
    ("Faturamento Cartão", "Auxiliares", "FORMAT([Faturamento], \"#,##0\", \"pt-BR\")", "General", "Faturamento arredondado sem abreviações, formatado para os cartões executivos."),
    ("Descontos", "Descontos", "SUMX(FILTER(fato_vendas, fato_vendas[status] = \"Entregue\"), fato_vendas[quantidade] * fato_vendas[preco_unitario] * fato_vendas[desconto_pct])", MONEY_FORMAT, "Valor de descontos concedidos em itens entregues."),
    ("Custo", "Custo", "SUMX(FILTER(fato_vendas, fato_vendas[status] = \"Entregue\"), fato_vendas[quantidade] * fato_vendas[custo_unitario])", MONEY_FORMAT, "Custo dos produtos efetivamente entregues."),
    ("Lucro", "Lucro", "[Faturamento] - [Custo]", MONEY_FORMAT, "Faturamento líquido menos custo dos itens entregues."),
    ("Lucro Cartão", "Auxiliares", "FORMAT([Lucro], \"#,##0\", \"pt-BR\")", "General", "Lucro arredondado sem abreviações, formatado para os cartões executivos."),
    ("Margem %", "Margem %", "DIVIDE([Lucro], [Faturamento])", PERCENT_FORMAT, "Lucro dividido pelo faturamento líquido."),
    ("Pedidos", "Pedidos", "CALCULATE(DISTINCTCOUNT(fato_vendas[id_pedido]), fato_vendas[status] = \"Entregue\")", "#,##0", "Quantidade de pedidos com itens entregues."),
    ("Ticket Médio", "Ticket Médio", "DIVIDE([Faturamento], [Pedidos])", MONEY_FORMAT, "Faturamento líquido por pedido com itens entregues."),
    ("Meta", "Meta", "CALCULATE(SUM(meta_mensal[valor_meta]), TREATAS(VALUES(dim_calendario[ano_mes_num]), meta_mensal[ano_mes_num]))", MONEY_FORMAT, "Meta mensal dos vendedores no contexto de calendário."),
    ("Atingimento da Meta %", "Meta", "DIVIDE([Faturamento], [Meta])", PERCENT_FORMAT, "Faturamento dividido pela meta do período."),
    ("Faturamento YTD", "Faturamento", "TOTALYTD([Faturamento], dim_calendario[data])", MONEY_FORMAT, "Faturamento acumulado desde o início do ano."),
    ("Faturamento mesmo período ano anterior", "Faturamento", "CALCULATE([Faturamento], SAMEPERIODLASTYEAR(dim_calendario[data]))", MONEY_FORMAT, "Faturamento no mesmo período do ano anterior."),
    ("Crescimento YoY %", "Faturamento", "VAR AnoAtual = MAX(dim_calendario[ano]) VAR Atual = CALCULATE([Faturamento], REMOVEFILTERS(dim_calendario[ano]), dim_calendario[ano] = AnoAtual) VAR Anterior = CALCULATE([Faturamento], REMOVEFILTERS(dim_calendario[ano]), dim_calendario[ano] = AnoAtual - 1) RETURN DIVIDE(Atual - Anterior, Anterior)", PERCENT_FORMAT, "Variação do ano mais recente no contexto em relação ao ano anterior, preservando outros filtros de calendário."),
    ("Taxa de Cancelamento %", "Pedidos", "DIVIDE(CALCULATE(COUNTROWS(fato_vendas), fato_vendas[status] = \"Cancelado\"), COUNTROWS(fato_vendas))", PERCENT_FORMAT, "Proporção de linhas de venda canceladas."),
    ("Taxa de Devolução %", "Pedidos", "DIVIDE(CALCULATE(COUNTROWS(fato_vendas), fato_vendas[status] = \"Devolvido\"), COUNTROWS(fato_vendas))", PERCENT_FORMAT, "Proporção de linhas de venda devolvidas."),
    ("Ranking de Vendedor", "Equipe Comercial", "RANKX(ALLSELECTED(dim_vendedor[nome_vendedor]), [Faturamento], , DESC, Dense)", "#,##0", "Posição do vendedor por faturamento no contexto selecionado."),
    ("Curva ABC de produtos", "Produto", "VAR Atual = [Faturamento] VAR Acumulado = SUMX(FILTER(ALLSELECTED(dim_produto[id_produto]), [Faturamento] >= Atual), [Faturamento]) VAR Percentual = DIVIDE(Acumulado, CALCULATE([Faturamento], ALLSELECTED(dim_produto[id_produto]))) RETURN SWITCH(TRUE(), Percentual <= 0.80, \"A\", Percentual <= 0.95, \"B\", \"C\")", "General", "Classe ABC do produto com base no faturamento acumulado."),
    ("Faturamento acumulado", "Faturamento", "VAR DataAtual = MAX(dim_calendario[data]) RETURN CALCULATE([Faturamento], FILTER(ALLSELECTED(dim_calendario[data]), dim_calendario[data] <= DataAtual))", MONEY_FORMAT, "Faturamento acumulado até a data no contexto atual."),
    ("ABC Acumulada %", "Produto", "VAR Atual = [Faturamento] VAR Acumulado = SUMX(FILTER(ALLSELECTED(dim_produto[id_produto]), [Faturamento] >= Atual), [Faturamento]) RETURN DIVIDE(Acumulado, CALCULATE([Faturamento], ALLSELECTED(dim_produto[id_produto])))", PERCENT_FORMAT, "Percentual acumulado de faturamento na ordem decrescente de produtos."),
    ("Preço Médio", "Rentabilidade", "DIVIDE(SUMX(FILTER(fato_vendas, fato_vendas[status] = \"Entregue\"), fato_vendas[quantidade] * fato_vendas[preco_unitario]), CALCULATE(SUM(fato_vendas[quantidade]), fato_vendas[status] = \"Entregue\"))", MONEY_FORMAT, "Preço médio ponderado por quantidade entregue."),
    ("Margem Unitária %", "Rentabilidade", "DIVIDE([Preço Médio] - DIVIDE([Custo], CALCULATE(SUM(fato_vendas[quantidade]), fato_vendas[status] = \"Entregue\")), [Preço Médio])", PERCENT_FORMAT, "Margem percentual unitária média no contexto."),
    ("Ranking Cliente", "Clientes", "RANKX(ALLSELECTED(dim_cliente[id_cliente]), [Faturamento], , DESC, Dense)", "#,##0", "Posição do cliente por faturamento."),
    ("Faturamento Top 10 Clientes", "Clientes", "IF([Ranking Cliente] <= 10, [Faturamento])", MONEY_FORMAT, "Exibe faturamento apenas para os dez clientes mais bem ranqueados."),
    ("Ticket Médio Top 10 Clientes", "Clientes", "IF([Ranking Cliente] <= 10, [Ticket Médio])", MONEY_FORMAT, "Exibe ticket médio apenas para os dez clientes mais bem ranqueados."),
    ("Indicador de Meta", "Equipe Comercial", "SWITCH(TRUE(), [Atingimento da Meta %] >= 1, \"Acima da meta\", [Atingimento da Meta %] >= 0.9, \"Atenção\", \"Abaixo da meta\")", "General", "Status textual de atingimento para leitura acessível além da cor."),
    ("Valor Etapa Cascata", "Rentabilidade", "VAR Etapa = SELECTEDVALUE(dim_etapa_cascata[etapa]) RETURN SWITCH(Etapa, \"Faturamento\", [Faturamento], \"Descontos\", -[Descontos], \"Custos\", -[Custo], \"Lucro\", [Lucro])", MONEY_FORMAT, "Valor calculado para cada etapa da cascata de rentabilidade."),
    ("Título Executivo", "Auxiliares", "\"Faturamento \" & IF([Crescimento YoY %] >= 0, \"cresce \", \"cai \") & FORMAT(ABS([Crescimento YoY %]), \"0.0%\") & \" no período\"", "General", "Texto dinâmico que resume a variação anual do faturamento."),
]


def build_model() -> None:
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Pasta de dados não encontrada: {DATA_DIR}")
    TABLES = [
        "fato_vendas", "dim_cliente", "dim_produto", "dim_vendedor",
        "dim_regiao", "dim_calendario", "meta_mensal", "dim_etapa_cascata",
    ]
    MODEL_DEFINITION = MODEL_DIR / "definition"
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DEFINITION.mkdir(parents=True, exist_ok=True)

    data_path = DEFAULT_POWER_QUERY_DATA_PATH
    (MODEL_DIR / "definition.pbism").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0",
    }, indent=2), encoding="utf-8")
    (MODEL_DEFINITION / "database.tmdl").write_text(
        "database VendasRentabilidade\n    compatibilityLevel: 1600\n",
        encoding="utf-8",
    )

    refs = "\n".join(f"ref table {tmdl_quote(table)}" for table in TABLES)
    model_text = (
        "model Model\n"
        "    culture: pt-BR\n"
        "    defaultPowerBIDataSourceVersion: powerBI_V3\n"
        "    sourceQueryCulture: pt-BR\n"
        "    dataAccessOptions\n"
        "        legacyRedirects\n"
        "        returnErrorValuesAsNull\n"
        f"\n{refs}\nref table _Medidas\n"
        "ref expression PastaDados\n"
    )
    (MODEL_DEFINITION / "model.tmdl").write_text(model_text, encoding="utf-8")
    (MODEL_DEFINITION / "expressions.tmdl").write_text(
        f"expression PastaDados = {m_text(data_path)} meta "
        "[IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n",
        encoding="utf-8",
    )

    for table in TABLES:
        columns = read_column_types(table)
        lines = [f"table {tmdl_quote(table)}", f"    lineageTag: {new_guid()}"]
        if table == "dim_calendario":
            lines.extend([
                "",
                "    annotation isDateTable = true",
                "    annotation dateColumnName = data",
            ])
        lines.extend(["", *column_tmdl(table, columns), ""])
        lines.append(build_partition(table, columns))
        (TABLE_DIR / f"{table}.tmdl").write_text("\n".join(lines), encoding="utf-8")

    measure_table = [
        "table _Medidas",
        f"    lineageTag: {new_guid()}",
        "    isHidden",
        "",
        "    column Auxiliar",
        "        dataType: string",
        "        isHidden",
        "        sourceColumn: Auxiliar",
        f"        lineageTag: {new_guid()}",
        "",
        "    partition _Medidas = m",
        "        mode: import",
        "        source =",
        "            #table({\"Auxiliar\"}, {})",
        "",
    ]
    for name, folder, expression, format_string, description in MEASURES:
        measure_table.extend([
            f"    /// {description}",
            f"    measure {tmdl_quote(name)} = {expression}",
            f"        formatString: {format_string}",
            f"        displayFolder: {folder}",
            f"        lineageTag: {new_guid()}",
            "",
        ])
    (TABLE_DIR / "_Medidas.tmdl").write_text("\n".join(measure_table), encoding="utf-8")

    rels = [
        ("fato_vendas", "data", "dim_calendario", "data"),
        ("fato_vendas", "id_cliente", "dim_cliente", "id_cliente"),
        ("fato_vendas", "id_produto", "dim_produto", "id_produto"),
        ("fato_vendas", "id_vendedor", "dim_vendedor", "id_vendedor"),
        ("fato_vendas", "id_regiao", "dim_regiao", "id_regiao"),
        ("meta_mensal", "id_vendedor", "dim_vendedor", "id_vendedor"),
    ]
    relationship_lines = []
    for fact_table, fact_column, dimension_table, dimension_column in rels:
        relationship_lines.extend([
            f"relationship {new_guid()}",
            f"    fromColumn: {tmdl_quote(fact_table)}.{tmdl_quote(fact_column)}",
            f"    toColumn: {tmdl_quote(dimension_table)}.{tmdl_quote(dimension_column)}",
            "    fromCardinality: many",
            "    toCardinality: one",
            "    crossFilteringBehavior: oneDirection",
            "    isActive: true",
            "",
        ])
    (MODEL_DEFINITION / "relationships.tmdl").write_text(
        "\n".join(relationship_lines), encoding="utf-8"
    )


def column_ref(table: str, column: str) -> dict:
    return {"Column": {
        "Expression": {"SourceRef": {"Entity": table}},
        "Property": column,
    }}


def measure_ref(name: str) -> dict:
    return {"Measure": {
        "Expression": {"SourceRef": {"Entity": "_Medidas"}},
        "Property": name,
    }}


def projection(table: str, name: str, is_measure: bool = False,
               display_name: str | None = None) -> dict:
    field = measure_ref(name) if is_measure else column_ref(table, name)
    return {
        "field": field,
        "queryRef": f"{table}.{name}" if not is_measure else f"_Medidas.{name}",
        "nativeQueryRef": name,
        **({"displayName": display_name} if display_name else {}),
    }


def visual_json(visual_type: str, fields: dict[str, list[dict]],
                x: int, y: int, width: int, height: int,
                title: str | None = None,
                sort_table: str | None = None, sort_column: str | None = None,
                sort_measure: str | None = None) -> dict:
    query_state = {
        role: {"projections": projections}
        for role, projections in fields.items()
    }
    visual_query = {"queryState": query_state}
    if (sort_table and sort_column) or (sort_table and sort_measure):
        sort_field = column_ref(sort_table, sort_column)
        if sort_measure:
            sort_field = measure_ref(sort_measure)
        visual_query["sortDefinition"] = {
            "sort": [{"field": sort_field, "direction": "Descending"}],
            "isDefaultSort": True,
        }
    visual = {
        "visualType": visual_type,
        "drillFilterOtherVisuals": True,
    }
    if visual_type != "pageNavigator":
        visual["query"] = visual_query
    container_objects = {}
    if title:
        container_objects["title"] = [{
            "properties": {
                "show": pbi_literal("true"),
                "text": pbi_literal(pbi_text_literal(title)),
                "fontFamily": pbi_literal("'Segoe UI Semibold'"),
                "fontSize": pbi_literal("12D"),
            }
        }]
    if visual_type in {
        "lineChart", "clusteredBarChart", "clusteredColumnChart",
        "lineClusteredColumnComboChart", "scatterChart", "waterfallChart", "treemap",
    }:
        container_objects["visualTooltip"] = [{
            "properties": {
                "show": pbi_literal("true"),
                "type": pbi_literal("'Canvas'"),
                "section": pbi_literal("'tooltip_kpi'"),
            }
        }]
    if container_objects:
        visual["visualContainerObjects"] = container_objects
    if visual_type != "pageNavigator":
        visual["visualContainerObjects"] = visual.get(
            "visualContainerObjects", {}
        )
        visual["visualContainerObjects"]["background"] = [{
            "properties": {
                "show": pbi_literal("true"),
                "color": {"solid": {"color": pbi_literal("'#FFFFFF'")}},
                "transparency": pbi_literal("0D"),
            }
        }]
        visual["visualContainerObjects"]["border"] = [{
            "properties": {
                "show": pbi_literal("true"),
                "color": {"solid": {"color": pbi_literal("'#D8E2EC'")}},
                "radius": pbi_literal("10D"),
                "width": pbi_literal("1D"),
            }
        }]
    if visual_type == "card":
        visual["objects"] = {
            "calloutValue": [{
                "properties": {
                    "labelDisplayUnits": pbi_literal("1D"),
                    "fontFamily": pbi_literal("'Segoe UI Semibold'"),
                    "fontSize": pbi_literal("16D"),
                    "color": {"solid": {"color": pbi_literal("'#183153'")}},
                }
            }]
        }
    elif visual_type == "slicer":
        visual["objects"] = {
            "data": [{
                "properties": {
                    "mode": pbi_literal("'Dropdown'"),
                },
            }],
        }
    elif visual_type == "pageNavigator":
        navigator_states = [
            ("default", "#1768AC"),
            ("hover", "#007C78"),
            ("selected", "#183153"),
            ("disabled", "#D8E2EC"),
        ]
        visual["objects"] = {
            "fill": [{
                "selector": {"id": state},
                "properties": {
                    "show": pbi_literal("true"),
                    "fillColor": {"solid": {"color": pbi_literal(f"'{color}'")}},
                    "transparency": pbi_literal("0D"),
                },
            } for state, color in navigator_states],
            "text": [{
                "selector": {"id": state},
                "properties": {
                    "show": pbi_literal("true"),
                    "fontColor": {
                        "solid": {
                            "color": pbi_literal(
                                "'#536579'" if state == "disabled" else "'#FFFFFF'"
                            )
                        }
                    },
                    "fontFamily": pbi_literal("'Segoe UI Semibold'"),
                    "fontSize": pbi_literal("11D"),
                },
            } for state, _color in navigator_states],
            "shape": [{
                "properties": {
                    "tileShape": pbi_literal("'rectangleRoundedByPixel'"),
                    "rectangleRoundedCurve": pbi_literal("8D"),
                },
            }],
        }
    elif visual_type in {
        "lineChart", "clusteredBarChart", "clusteredColumnChart",
        "lineClusteredColumnComboChart", "scatterChart", "waterfallChart",
        "treemap",
    }:
        accent_colors = {
            "lineChart": "#1768AC",
            "clusteredBarChart": "#007C78",
            "clusteredColumnChart": "#B7791F",
            "lineClusteredColumnComboChart": "#6C5B9B",
            "scatterChart": "#6C5B9B",
            "waterfallChart": "#C44E52",
            "treemap": "#007C78",
        }
        visual["objects"] = {
            "categoryAxis": [{
                "properties": {
                    "fontFamily": pbi_literal("'Segoe UI'"),
                    "fontSize": pbi_literal("10D"),
                    "labelColor": {"solid": {"color": pbi_literal("'#536579'")}},
                    "showAxisTitle": pbi_literal("false"),
                }
            }],
            "valueAxis": [{
                "properties": {
                    "fontFamily": pbi_literal("'Segoe UI'"),
                    "fontSize": pbi_literal("10D"),
                    "labelColor": {"solid": {"color": pbi_literal("'#536579'")}},
                    "labelDisplayUnits": pbi_literal("1D"),
                    "showAxisTitle": pbi_literal("false"),
                    "gridlineShow": pbi_literal("true"),
                    "gridlineColor": {"solid": {"color": pbi_literal("'#E7EDF3'")}},
                }
            }],
            "labels": [{
                "properties": {
                    "fontFamily": pbi_literal("'Segoe UI'"),
                    "fontSize": pbi_literal("10D"),
                    "labelDisplayUnits": pbi_literal("1D"),
                }
            }],
        }
        if visual_type != "treemap":
            accent = pbi_literal(f"'{accent_colors[visual_type]}'")
            visual["objects"]["dataPoint"] = [{
                "properties": {
                    "defaultColor": {"solid": {"color": accent}},
                    "fill": {"solid": {"color": accent}},
                }
            }]
    return {
        "$schema": SCHEMAS["visual"],
        "name": new_guid(),
        "position": {
            "x": x, "y": y, "z": 0, "height": height, "width": width,
            "tabOrder": y * 100 + x,
        },
        "visual": visual,
    }


def column_projection(table: str, name: str, display: str | None = None) -> dict:
    return projection(table, name, False, display)


def measure_projection(name: str, display: str | None = None) -> dict:
    return projection("_Medidas", name, True, display)


def chart(visual_type: str, role_fields: dict[str, list[dict]],
          position: tuple[int, int, int, int],
          title_override: str | None = None,
          **sort_options) -> dict:
    x, y, width, height = position
    is_executive_title = False
    if visual_type == "pageNavigator":
        title = None
    elif visual_type == "card":
        first = next(iter(role_fields.values()), [])
        is_executive_title = bool(
            first and first[0].get("nativeQueryRef") == "Título Executivo"
        )
        title = (
            first[0].get("displayName") or first[0].get("nativeQueryRef")
            if first else None
        )
        if is_executive_title:
            title = None
            height = 58
    else:
        measure_names = [
            item.get("displayName") or item.get("nativeQueryRef", "")
            for projections in role_fields.values()
            for item in projections
            if item.get("queryRef", "").startswith("_Medidas.")
        ]
        category_names = [
            item.get("displayName") or item.get("nativeQueryRef", "")
            for role, projections in role_fields.items()
            if role in {"Category", "Rows"}
            for item in projections
            if not item.get("queryRef", "").startswith("_Medidas.")
        ]
        title = " e ".join(measure_names[:2])
        if category_names and measure_names:
            category_labels = {
                "nome_mes": "mês",
                "ano_mes": "mês",
                "regiao": "região",
                "uf": "estado",
                "segmento": "segmento",
                "categoria": "categoria",
                "subcategoria": "subcategoria",
                "nome_vendedor": "vendedor",
                "nome_cliente": "cliente",
                "nome_produto": "produto",
                "etapa": "etapa",
            }
            categories = [
                category_labels.get(name, name.replace("_", " "))
                for name in category_names[:2]
            ]
            title += " por " + " / ".join(categories)
        elif not title:
            title = visual_type
    if title_override:
        title = title_override
    result = visual_json(
        visual_type, role_fields, x, y, width, height, title=title, **sort_options
    )
    return result


def specs() -> list[dict]:
    kpi_layout = [
        (24, 126, 606, 88),
        (650, 126, 606, 88),
        (24, 226, 386, 76),
        (435, 226, 386, 76),
        (846, 226, 410, 76),
    ]
    exec_kpis = ["Faturamento", "Lucro", "Margem %", "Atingimento da Meta %", "Crescimento YoY %"]
    kpi_labels = {
        "Faturamento": "Faturamento (R$)",
        "Lucro": "Lucro (R$)",
        "Atingimento da Meta %": "Atingimento da meta",
        "Crescimento YoY %": "Crescimento anual",
    }
    kpi_fields = {
        "Faturamento": "Faturamento Cartão",
        "Lucro": "Lucro Cartão",
    }
    pages = []
    pages.append({
        "name": "visao_executiva", "displayName": "Visão Executiva",
        "visuals": [
            chart("pageNavigator", {}, (24, 18, 1232, 34)),
            chart("card", {"Data": [measure_projection("Título Executivo")]},
                  (24, 62, 1232, 48)),
            *[
                chart(
                    "card",
                    {"Data": [measure_projection(
                        kpi_fields.get(measure, measure),
                        kpi_labels.get(measure),
                    )]},
                    pos,
                )
                for measure, pos in zip(exec_kpis, kpi_layout, strict=True)
            ],
            chart("lineChart", {
                "Category": [column_projection("dim_calendario", "nome_mes", "Mês")],
                "Y": [measure_projection("Faturamento")],
                "Legend": [column_projection("dim_calendario", "ano", "Ano")],
            }, (24, 316, 790, 232), title_override="Evolução mensal do faturamento"),
            chart("clusteredBarChart", {
                "Category": [column_projection("dim_regiao", "regiao", "Região")],
                "Y": [measure_projection("Faturamento")],
            }, (830, 316, 426, 232), title_override="Faturamento por região"),
            chart("slicer", {"Values": [column_projection("dim_calendario", "ano", "Ano")]},
                  (24, 562, 386, 118), title_override="Ano"),
            chart("slicer", {"Values": [column_projection("fato_vendas", "canal", "Canal de venda")]},
                  (435, 562, 386, 118), title_override="Canal de venda"),
            chart("slicer", {"Values": [column_projection("dim_produto", "categoria", "Categoria")]},
                  (846, 562, 410, 118), title_override="Categoria"),
        ],
    })
    pages.append({
        "name": "vendas_produto", "displayName": "Vendas por Produto",
        "visuals": [
            chart("pageNavigator", {}, (24, 18, 1232, 34)),
            chart("clusteredBarChart", {
                "Category": [column_projection("dim_produto", "categoria")],
                "Y": [measure_projection("Faturamento")],
            }, (24, 78, 790, 330), title_override="Faturamento por categoria",
                sort_table="_Medidas", sort_measure="Faturamento"),
            chart("treemap", {
                "Group": [column_projection("dim_produto", "categoria")],
                "Details": [column_projection("dim_produto", "subcategoria")],
                "Values": [measure_projection("Faturamento")],
            }, (830, 78, 426, 330), title_override="Participação por categoria e subcategoria"),
            chart("matrix", {
                "Rows": [column_projection("dim_produto", "categoria"),
                         column_projection("dim_produto", "subcategoria")],
                "Values": [measure_projection("Faturamento"),
                           measure_projection("Margem %"),
                           measure_projection("Curva ABC de produtos")],
            }, (24, 430, 1232, 245)),
        ],
    })
    pages.append({
        "name": "clientes", "displayName": "Clientes",
        "visuals": [
            chart("pageNavigator", {}, (24, 18, 1232, 34)),
            chart("tableEx", {
                "Values": [column_projection("dim_cliente", "nome_cliente"),
                           column_projection("dim_cliente", "segmento"),
                           column_projection("dim_cliente", "cidade"),
                           column_projection("dim_cliente", "uf"),
                           measure_projection("Faturamento Top 10 Clientes"),
                           measure_projection("Ticket Médio Top 10 Clientes")],
            }, (24, 345, 1232, 330), title_override="Ranking de clientes por faturamento",
                sort_table="_Medidas", sort_measure="Faturamento Top 10 Clientes"),
            chart("clusteredBarChart", {
                "Category": [column_projection("dim_cliente", "uf")],
                "Y": [measure_projection("Faturamento")],
            }, (24, 78, 790, 250), title_override="Faturamento por estado"),
            chart("clusteredColumnChart", {
                "Category": [column_projection("dim_cliente", "segmento")],
                "Y": [measure_projection("Ticket Médio")],
            }, (830, 78, 426, 250), title_override="Ticket médio por segmento"),
        ],
    })
    pages.append({
        "name": "equipe_comercial", "displayName": "Equipe Comercial",
        "visuals": [
            chart("pageNavigator", {}, (24, 18, 1232, 34)),
            chart("clusteredBarChart", {
                "Category": [column_projection("dim_vendedor", "nome_vendedor")],
                "Y": [measure_projection("Faturamento")],
            }, (24, 78, 790, 330), title_override="Ranking de faturamento por vendedor",
                sort_table="_Medidas", sort_measure="Faturamento"),
            chart("clusteredColumnChart", {
                "Category": [column_projection("dim_vendedor", "equipe")],
                "Y": [measure_projection("Faturamento"), measure_projection("Meta")],
            }, (830, 78, 426, 330), title_override="Realizado e meta por equipe"),
            chart("tableEx", {
                "Values": [column_projection("dim_vendedor", "nome_vendedor"),
                           column_projection("dim_vendedor", "equipe"),
                           measure_projection("Faturamento"),
                           measure_projection("Meta"),
                           measure_projection("Atingimento da Meta %"),
                           measure_projection("Indicador de Meta"),
                           measure_projection("Ranking de Vendedor")],
            }, (24, 430, 1232, 245), title_override="Atingimento e posição",
                sort_table="_Medidas", sort_measure="Faturamento"),
        ],
    })
    pages.append({
        "name": "rentabilidade", "displayName": "Rentabilidade",
        "visuals": [
            chart("pageNavigator", {}, (24, 18, 1232, 34)),
            chart("clusteredBarChart", {
                "Category": [column_projection("dim_produto", "categoria")],
                "Y": [measure_projection("Margem %")],
            }, (24, 78, 390, 285), title_override="Margem por categoria"),
            chart("clusteredColumnChart", {
                "Category": [column_projection("dim_produto", "categoria")],
                "Y": [measure_projection("Preço Médio")],
            }, (435, 78, 390, 285), title_override="Preço médio por categoria"),
            chart("waterfallChart", {
                "Category": [column_projection("dim_etapa_cascata", "etapa")],
                "Y": [measure_projection("Valor Etapa Cascata")],
            }, (846, 78, 410, 285), title_override="Da receita ao lucro"),
            chart("lineChart", {
                "Category": [column_projection("dim_calendario", "ano_mes")],
                "Y": [measure_projection("Margem %")],
            }, (24, 390, 550, 250), title_override="Evolução mensal da margem"),
            chart("matrix", {
                "Rows": [column_projection("dim_produto", "categoria")],
                "Values": [measure_projection("Faturamento"),
                           measure_projection("Lucro"),
                           measure_projection("Margem %")],
            }, (590, 390, 666, 250), title_override="Resumo de rentabilidade"),
        ],
    })
    pages.append({
        "name": "detalhe_vendedor", "displayName": "Detalhe do Vendedor",
        "type": "Drillthrough",
        "visibility": "HiddenInViewMode",
        "pageBinding": {
            "name": "DetalheVendedor",
            "type": "Drillthrough",
            "parameters": [{
                "name": "id_vendedor",
                "boundFilter": "id_vendedor",
                "fieldExpr": column_ref("dim_vendedor", "id_vendedor"),
                "qnaSingleSelectRequired": True,
            }],
            "acceptsFilterContext": "Default",
        },
        "visuals": [
            chart("card", {"Data": [measure_projection("Faturamento Cartão", "Faturamento (R$)")]}, (24, 78, 390, 96)),
            chart("card", {"Data": [measure_projection("Atingimento da Meta %")]}, (430, 78, 260, 96)),
            chart("card", {"Data": [measure_projection("Margem %")]}, (700, 78, 260, 96)),
            chart("card", {"Data": [measure_projection("Ranking de Vendedor")]}, (970, 78, 286, 96)),
            chart("lineChart", {
                "Category": [column_projection("dim_calendario", "ano_mes")],
                "Y": [measure_projection("Faturamento")],
            }, (24, 198, 790, 340), title_override="Evolução de faturamento do vendedor"),
            chart("tableEx", {
                "Values": [column_projection("dim_cliente", "nome_cliente"),
                           column_projection("dim_cliente", "segmento"),
                           measure_projection("Faturamento")],
            }, (830, 198, 426, 340), title_override="Principais clientes",
                sort_table="_Medidas", sort_measure="Faturamento"),
        ],
    })
    pages.append({
        "name": "tooltip_kpi", "displayName": "Tooltip - Mini KPIs",
        "type": "Tooltip",
        "visibility": "HiddenInViewMode",
        "pageBinding": {"name": "TooltipMiniKpis", "type": "Tooltip"},
        "visuals": [
            chart("card", {"Data": [measure_projection("Faturamento Cartão", "Faturamento (R$)")]}, (8, 8, 400, 58)),
            chart("card", {"Data": [measure_projection("Margem %")]}, (8, 74, 400, 58)),
            chart("card", {"Data": [measure_projection("Ticket Médio")]}, (8, 140, 400, 58)),
        ],
    })
    return pages


def build_report() -> None:
    DEFINITION_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "definition.pbir").write_text(json.dumps({
        "$schema": SCHEMAS["pbir"],
        "version": "4.0",
        "datasetReference": {"byPath": {"path": "../VendasRentabilidade.SemanticModel"}},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    theme = {
        "name": "Vendas e Rentabilidade",
        "dataColors": ["#183153", "#007C78", "#1768AC", "#C44E52", "#B7791F", "#6C5B9B"],
        "background": "#F2F6FA",
        "foreground": "#24364B",
        "tableAccent": "#1768AC",
        "good": "#007C78",
        "neutral": "#B7791F",
        "bad": "#C44E52",
        "textClasses": {
            "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 18, "color": "#183153"},
            "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": "#536579"},
            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 14, "color": "#183153"},
            "header": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": "#183153"},
        },
        "visualStyles": {
            "*": {
                "*": {
                    "background": [{
                        "show": True,
                        "color": {"solid": {"color": "#FFFFFF"}},
                        "transparency": 0,
                    }],
                    "border": [{
                        "show": True,
                        "color": {"solid": {"color": "#D8E2EC"}},
                        "radius": 10,
                        "width": 1,
                    }],
                    "categoryAxis": [{
                        "fontFamily": "Segoe UI",
                        "fontSize": 10,
                        "labelColor": {"solid": {"color": "#536579"}},
                    }],
                    "valueAxis": [{
                        "fontFamily": "Segoe UI",
                        "fontSize": 10,
                        "labelColor": {"solid": {"color": "#536579"}},
                        "labelDisplayUnits": 1,
                        "gridlineShow": True,
                        "gridlineColor": {"solid": {"color": "#E7EDF3"}},
                    }],
                    "labels": [{
                        "fontFamily": "Segoe UI",
                        "fontSize": 10,
                        "labelDisplayUnits": 1,
                    }],
                    "dataPoint": [{
                        "defaultColor": {"solid": {"color": "#1768AC"}},
                    }],
                }
            },
            "pageNavigator": {
                "*": {
                    "layout": [{"orientation": 2, "columnCount": 7, "cellPadding": 4}],
                    "fill": [
                        {"$id": "default", "show": True, "fillColor": {"solid": {"color": "#1768AC"}}, "transparency": 0},
                        {"$id": "hover", "show": True, "fillColor": {"solid": {"color": "#007C78"}}, "transparency": 0},
                        {"$id": "selected", "show": True, "fillColor": {"solid": {"color": "#183153"}}, "transparency": 0},
                        {"$id": "disabled", "show": True, "fillColor": {"solid": {"color": "#D8E2EC"}}, "transparency": 0},
                    ],
                    "text": [
                        {"$id": "default", "show": True, "fontColor": {"solid": {"color": "#FFFFFF"}}, "fontFamily": "Segoe UI Semibold", "fontSize": 11},
                        {"$id": "hover", "show": True, "fontColor": {"solid": {"color": "#FFFFFF"}}, "fontFamily": "Segoe UI Semibold", "fontSize": 11},
                        {"$id": "selected", "show": True, "fontColor": {"solid": {"color": "#FFFFFF"}}, "fontFamily": "Segoe UI Semibold", "fontSize": 11},
                        {"$id": "disabled", "show": True, "fontColor": {"solid": {"color": "#536579"}}, "fontFamily": "Segoe UI Semibold", "fontSize": 11},
                    ],
                    "shape": [{"tileShape": "rectangleRoundedByPixel", "rectangleRoundedCurve": 8}],
                }
            },
            "card": {
                "*": {
                    "calloutValue": [{
                        "color": {"solid": {"color": "#183153"}},
                        "fontSize": 18,
                        "fontFamily": "Segoe UI Semibold",
                    }],
                    "border": [{
                        "show": True,
                        "color": {"solid": {"color": "#D8E2EC"}},
                        "radius": 8,
                        "width": 1,
                    }],
                    "dropShadow": [{
                        "show": True,
                        "preset": "BottomRight",
                        "position": "Outer",
                        "color": {"solid": {"color": "#183153"}},
                        "transparency": 88,
                        "shadowSpread": 1,
                        "shadowBlur": 4,
                        "angle": 45,
                        "shadowDistance": 2,
                    }],
                }
            },
        },
    }
    resource_dir = REPORT_DIR / "StaticResources" / "RegisteredResources"
    resource_dir.mkdir(parents=True, exist_ok=True)
    (resource_dir / "VendasRentabilidade.json").write_text(
        json.dumps(theme, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    theme_version = {"visual": "2.14.0", "page": "2.1.0", "report": "3.3.0"}
    report_json = {
        "$schema": SCHEMAS["report"],
        "themeCollection": {
            "baseTheme": {
                "name": "CY24SU06",
                "reportVersionAtImport": theme_version,
                "type": "SharedResources",
            },
            "customTheme": {
                "name": "Vendas e Rentabilidade",
                "reportVersionAtImport": theme_version,
                "type": "RegisteredResources",
            },
        },
        "objects": {
            "section": [{
                "properties": {
                    "verticalAlignment": pbi_literal("'Top'"),
                },
            }],
            "outspacePane": [{
                "properties": {
                    "expanded": pbi_literal("false"),
                },
            }],
        },
        "resourcePackages": [
            {
                "name": "SharedResources",
                "type": "SharedResources",
                "items": [{
                    "name": "CY24SU06",
                    "path": "BaseThemes/CY24SU06.json",
                    "type": "BaseTheme",
                }],
            },
            {
                "name": "RegisteredResources",
                "type": "RegisteredResources",
                "items": [{
                    "name": "VendasRentabilidade.json",
                    "path": "VendasRentabilidade.json",
                    "type": "CustomTheme",
                }],
            },
        ],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
    }
    (DEFINITION_DIR / "report.json").write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pages = specs()
    page_root = DEFINITION_DIR / "pages"
    page_root.mkdir(parents=True, exist_ok=True)
    for page_spec in pages:
        page_name = page_spec["name"]
        page_folder = page_root / page_name
        visual_root = page_folder / "visuals"
        visual_root.mkdir(parents=True, exist_ok=True)
        for index, visual in enumerate(page_spec["visuals"]):
            visual["name"] = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"VendasRentabilidade:{page_name}:visual:{index}",
            ))
        expected_visuals = {visual["name"] for visual in page_spec["visuals"]}
        for existing in visual_root.iterdir():
            if existing.is_dir() and existing.name not in expected_visuals:
                shutil.rmtree(existing)
        page_json = {
            "$schema": SCHEMAS["page"],
            "name": page_name,
            "displayName": page_spec["displayName"],
            "displayOption": "FitToPage",
            "width": 1280 if page_name != "tooltip_kpi" else 420,
            "height": 720 if page_name != "tooltip_kpi" else 220,
        }
        if page_name != "tooltip_kpi":
            page_json["objects"] = {
                "background": [{
                    "properties": {
                        "color": {
                            "solid": {
                                "color": pbi_literal("'#F2F6FA'"),
                            },
                        },
                        "transparency": pbi_literal("0D"),
                    },
                }],
            }
        for key in ("type", "visibility", "pageBinding"):
            if key in page_spec:
                page_json[key] = page_spec[key]
        (page_folder / "page.json").write_text(
            json.dumps(page_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for visual in page_spec["visuals"]:
            visual_name = visual["name"]
            (visual_root / visual_name).mkdir(parents=True, exist_ok=True)
            (visual_root / visual_name / "visual.json").write_text(
                json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    (DEFINITION_DIR / "pages" / "pages.json").write_text(json.dumps({
        "$schema": SCHEMAS["pages"],
        "pageOrder": [page["name"] for page in pages],
        "activePageName": "visao_executiva",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEFINITION_DIR / "version.json").write_text(json.dumps({
        "$schema": SCHEMAS["version"],
        "version": "2.0.0",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (ROOT / "VendasRentabilidade.pbip").write_text(json.dumps({
        "$schema": SCHEMAS["pbip"],
        "version": "1.0",
        "artifacts": [{"report": {"path": "VendasRentabilidade.Report"}}],
        "settings": {"enableAutoRecovery": True},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    for expected in ("fato_vendas.csv", "dim_calendario.csv", "meta_mensal.csv"):
        if not (DATA_DIR / expected).exists():
            raise FileNotFoundError(f"Gere e trate os CSVs antes de criar o projeto: {expected}")
    build_model()
    build_report()
    print(f"Projeto PBIP criado: {ROOT / 'VendasRentabilidade.pbip'}")


if __name__ == "__main__":
    main()
