from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_CACHE = Path(__file__).resolve().parent / "schemas"
SCHEMA_URLS = {
    "pbip": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
    "pbir": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
    "report": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
    "page": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
    "pages": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
    "version": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
    "visual": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.13.0/schema.json",
    "semantic_model": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
    "theme": "https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.159.json",
}
COMPATIBILITY_NOTES: set[str] = set()
GUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
TABLE_RE = re.compile(r"^table\s+(?:'([^']+)'|([^\s]+))\s*$", re.MULTILINE)
COLUMN_RE = re.compile(r"^\s+column\s+(?:'([^']+)'|([^\s]+))\s*$", re.MULTILINE)
MEASURE_RE = re.compile(r"^\s+measure\s+(?:'([^']+)'|([^\s=]+))\s*=", re.MULTILINE)
RELATIONSHIP_FROM_RE = re.compile(
    r"^\s+fromColumn:\s+(?:'([^']+)'|([A-Za-z0-9_]+))\.(?:'([^']+)'|([A-Za-z0-9_]+))",
    re.MULTILINE,
)
RELATIONSHIP_TO_RE = re.compile(
    r"^\s+toColumn:\s+(?:'([^']+)'|([A-Za-z0-9_]+))\.(?:'([^']+)'|([A-Za-z0-9_]+))",
    re.MULTILINE,
)


def load_schema(uri: str) -> dict:
    parsed = urlparse(uri)
    if parsed.scheme != "https" or parsed.netloc not in {
        "developer.microsoft.com", "raw.githubusercontent.com"
    }:
        raise ValueError(f"Referência de schema externa não permitida: {uri}")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", uri)
    cache_path = SCHEMA_CACHE / f"{safe_name}.json"
    if cache_path.exists():
        schema = json.loads(cache_path.read_text(encoding="utf-8"))
        schema["$id"] = uri
        return schema
    request = urllib.request.Request(
        uri, headers={"User-Agent": "VendasRentabilidade-PBIP-validator/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code != 404 or not uri.startswith(
            "https://developer.microsoft.com/json-schemas/"
        ):
            raise
        raw_uri = uri.replace(
            "https://developer.microsoft.com/json-schemas/",
            "https://raw.githubusercontent.com/microsoft/json-schemas/main/",
            1,
        )
        raw_request = urllib.request.Request(
            raw_uri, headers={"User-Agent": "VendasRentabilidade-PBIP-validator/1.0"}
        )
        with urllib.request.urlopen(raw_request, timeout=20) as response:
            content = response.read().decode("utf-8")
    schema = json.loads(content)
    schema["$id"] = uri
    SCHEMA_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    return schema


def validate_json(path: Path, schema_url: str, issues: list[str]) -> None:
    try:
        instance = json.loads(path.read_text(encoding="utf-8"))
        actual_schema = instance.get("$schema")
        if path.name == "visual.json" and actual_schema != schema_url:
            if (
                actual_schema
                == "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/visualContainer/2.14.0/schema.json"
                and schema_url == SCHEMA_URLS["visual"]
            ):
                instance["$schema"] = schema_url
                COMPATIBILITY_NOTES.add(
                    "Desktop grava visuais PBIR 2.14.0, ainda sem schema oficial "
                    "publicado; os arquivos foram verificados por compatibilidade "
                    "estrutural com o schema oficial 2.13.0."
                )
            else:
                issues.append(
                    f"{path.relative_to(ROOT)}: schema declarado incompatível "
                    f"com a validação: {actual_schema}."
                )
                return
        schema = load_schema(schema_url)
        Draft7Validator.check_schema(schema)
        registry = Registry(
            retrieve=lambda uri: Resource.from_contents(
                load_schema(str(uri)), default_specification=DRAFT7
            )
        )
        errors = sorted(
            Draft7Validator(schema, registry=registry).iter_errors(instance),
            key=lambda item: list(item.absolute_path),
        )
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "(raiz)"
            issues.append(f"{path.relative_to(ROOT)}: {location}: {error.message}")
    except Exception as error:
        source = getattr(error, "url", "")
        issues.append(
            f"{path.relative_to(ROOT)}: falha ao validar JSON/schema: {error}"
            + (f" ({source})" if source else "")
        )


def table_name(match: re.Match) -> str:
    return match.group(1) or match.group(2)


def parse_tmdl(issues: list[str]) -> tuple[dict[str, set[str]], dict[str, set[str]], list[str], list[str]]:
    table_dir = ROOT / "VendasRentabilidade.SemanticModel" / "definition" / "tables"
    columns: dict[str, set[str]] = {}
    measures: dict[str, set[str]] = {}
    tmdl_files = sorted(table_dir.glob("*.tmdl"))
    if not tmdl_files:
        raise FileNotFoundError(f"Arquivos TMDL ausentes: {table_dir}")
    for path in tmdl_files:
        text = path.read_text(encoding="utf-8")
        if "Table.TransformColumnTypes" in text and '"en-US"' not in text:
            issues.append(
                f"{path.relative_to(ROOT)}: cultura de leitura CSV deve ser en-US "
                "para preservar os pontos decimais."
            )
        table_match = TABLE_RE.search(text)
        if not table_match:
            raise ValueError(f"Não foi encontrada a declaração table em {path}")
        table = table_name(table_match)
        columns[table] = {
            match.group(1) or match.group(2) for match in COLUMN_RE.finditer(text)
        }
        measures[table] = {
            match.group(1) or match.group(2) for match in MEASURE_RE.finditer(text)
        }
    return columns, measures, [str(path) for path in tmdl_files], [
        (ROOT / "VendasRentabilidade.SemanticModel" / "definition" / "relationships.tmdl").read_text(
            encoding="utf-8"
        )
    ]


def validate_model(issues: list[str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    columns, measures, tmdl_files, relationship_texts = parse_tmdl(issues)
    calendar_path = (
        ROOT / "VendasRentabilidade.SemanticModel" / "definition" / "tables"
        / "dim_calendario.tmdl"
    )
    calendar_text = calendar_path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^\s+annotation isDateTable = true\s*$", calendar_text):
        issues.append("dim_calendario não está marcada como tabela de datas no TMDL.")
    if not re.search(r"(?m)^\s+annotation dateColumnName = data\s*$", calendar_text):
        issues.append("A coluna de data de dim_calendario não está declarada no TMDL.")
    if re.search(r"(?m)^\s+isDateTable\s*$", calendar_text):
        issues.append("TMDL contém a propriedade inválida isDateTable sem annotation.")
    measure_path = (
        ROOT / "VendasRentabilidade.SemanticModel" / "definition" / "tables"
        / "_Medidas.tmdl"
    )
    measure_text = measure_path.read_text(encoding="utf-8")
    measure_count = len(measures.get("_Medidas", set()))
    documentation_count = len(re.findall(r"(?m)^\s+///\s+.+$", measure_text))
    if documentation_count != measure_count:
        issues.append(
            f"Documentação TMDL de medidas incompleta: "
            f"{documentation_count}/{measure_count} comentários."
        )
    if re.search(r"(?m)^\s+description\s*:", measure_text):
        issues.append("TMDL contém a propriedade description que o Desktop rejeita.")
    for measure_name in ("Faturamento Cartão", "Lucro Cartão"):
        expression = re.search(
            rf"(?m)^\s*measure '{re.escape(measure_name)}' = FORMAT\(",
            measure_text,
        )
        if not expression:
            issues.append(
                f"A medida '{measure_name}' deve formatar o KPI monetário como texto "
                "para impedir abreviações automáticas no cartão."
            )
    all_names = {}
    for table, names in columns.items():
        for name in names:
            all_names.setdefault(name.casefold(), []).append(f"coluna {table}.{name}")
    for table, names in measures.items():
        for name in names:
            if name.casefold() in all_names:
                issues.append(
                    f"Medida '{name}' repete o nome de coluna: "
                    + ", ".join(all_names[name.casefold()])
                )
    guids: dict[str, str] = {}
    for path in (ROOT / "VendasRentabilidade.SemanticModel" / "definition").rglob("*.tmdl"):
        for guid in GUID_RE.findall(path.read_text(encoding="utf-8")):
            if guid.lower() in guids:
                issues.append(
                    f"GUID duplicado em TMDL: {guid} ({guids[guid.lower()]} e {path})"
                )
            else:
                guids[guid.lower()] = str(path)

    relationships = relationship_texts[0]
    from_refs = RELATIONSHIP_FROM_RE.findall(relationships)
    to_refs = RELATIONSHIP_TO_RE.findall(relationships)
    blocks = re.split(r"(?m)^relationship\s+", relationships)[1:]
    if len(from_refs) != len(to_refs) or len(blocks) != len(from_refs):
        issues.append("Estrutura inconsistente em relationships.tmdl.")
    pairs = set()
    for block, from_match, to_match in zip(blocks, from_refs, to_refs):
        from_table, from_column = (from_match[0] or from_match[1], from_match[2] or from_match[3])
        to_table, to_column = (to_match[0] or to_match[1], to_match[2] or to_match[3])
        if from_table not in columns or from_column not in columns[from_table]:
            issues.append(f"Relacionamento aponta para campo inexistente: {from_table}.{from_column}")
        if to_table not in columns or to_column not in columns[to_table]:
            issues.append(f"Relacionamento aponta para campo inexistente: {to_table}.{to_column}")
        pair = tuple(sorted((from_table, to_table)))
        if pair in pairs:
            issues.append(f"Relacionamento duplicado/ambíguo entre {from_table} e {to_table}.")
        pairs.add(pair)
        from_cardinality = re.search(r"(?m)^\s+fromCardinality:\s*(\w+)", block)
        to_cardinality = re.search(r"(?m)^\s+toCardinality:\s*(\w+)", block)
        if from_cardinality and from_cardinality.group(1) != "many":
            issues.append(f"Relacionamento não está configurado como muitos-para-um: {from_table}->{to_table}")
        if to_cardinality and to_cardinality.group(1) != "one":
            issues.append(f"Relacionamento não está configurado como muitos-para-um: {from_table}->{to_table}")
        cross_filtering = re.search(r"(?m)^\s+crossFilteringBehavior:\s*(\w+)", block)
        if cross_filtering and cross_filtering.group(1) != "oneDirection":
            issues.append(f"Relacionamento sem filtro unidirecional: {from_table}->{to_table}")
    if len(blocks) != 6:
        issues.append(f"Esperados 6 relacionamentos ativos; encontrados {len(blocks)}.")
    return columns, measures


def walk_field_refs(value):
    if isinstance(value, dict):
        for kind in ("Column", "Measure"):
            if kind in value and isinstance(value[kind], dict):
                node = value[kind]
                entity = node.get("Expression", {}).get("SourceRef", {}).get("Entity")
                prop = node.get("Property")
                if entity and prop:
                    yield kind, entity, prop
        for child in value.values():
            yield from walk_field_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_field_refs(child)


def validate_report_fields(columns: dict[str, set[str]],
                           measures: dict[str, set[str]],
                           issues: list[str]) -> int:
    definition = ROOT / "VendasRentabilidade.Report" / "definition"
    visual_paths = sorted(definition.glob("pages/*/visuals/*/visual.json"))
    supported_visual_types = {
        "card",
        "clusteredBarChart",
        "clusteredColumnChart",
        "lineChart",
        "lineClusteredColumnComboChart",
        "matrix",
        "pageNavigator",
        "scatterChart",
        "slicer",
        "tableEx",
        "treemap",
        "waterfallChart",
    }
    if not visual_paths:
        issues.append("Nenhum visual PBIR foi gerado.")
    all_visual_names: set[str] = set()
    for path in visual_paths:
        visual = json.loads(path.read_text(encoding="utf-8"))
        page_path = path.parents[2] / "page.json"
        page = json.loads(page_path.read_text(encoding="utf-8"))
        position = visual.get("position", {})
        if all(key in position for key in ("x", "y", "width", "height")):
            right = position["x"] + position["width"]
            bottom = position["y"] + position["height"]
            if right > page.get("width", 1280) + 0.1 or bottom > page.get("height", 720) + 0.1:
                issues.append(
                    f"{path.relative_to(ROOT)}: visual ultrapassa o canvas da página "
                    f"({right:g}×{bottom:g} em {page.get('width')}×{page.get('height')})."
                )
        name = visual.get("name")
        if name in all_visual_names:
            issues.append(f"GUID/nome visual duplicado: {name}")
        all_visual_names.add(name)
        visual_definition = visual.get("visual", {})
        visual_type = visual_definition.get("visualType")
        if path.parents[2].name == "clientes" and visual_type == "tableEx":
            top10_measures = {
                prop for kind, _entity, prop in walk_field_refs(visual)
                if kind == "Measure"
            }
            if not {
                "Faturamento Top 10 Clientes",
                "Ticket Médio Top 10 Clientes",
            } <= top10_measures:
                issues.append(
                    f"{path.relative_to(ROOT)}: tabela de clientes deve usar as "
                    "medidas do Top 10."
                )
        if visual_type not in supported_visual_types:
            issues.append(
                f"{path.relative_to(ROOT)}: tipo de visual não suportado "
                f"ou desconhecido: {visual_type}."
            )
        if visual_type == "pageNavigator" and "query" in visual_definition:
            issues.append(
                f"{path.relative_to(ROOT)}: pageNavigator não deve conter query."
            )
        if visual_type == "card":
            callout = visual_definition.get("objects", {}).get("calloutValue", [])
            if callout and callout[0].get("properties", {}).get(
                "labelDisplayUnits", {}
            ).get("expr", {}).get("Literal", {}).get("Value") != "1D":
                issues.append(
                    f"{path.relative_to(ROOT)}: cartão deve exibir o valor completo, "
                    "sem abreviação automática."
                )
            card_fields = list(walk_field_refs(visual))
            if any(
                kind == "Measure" and prop == "Título Executivo"
                for kind, _entity, prop in card_fields
            ):
                if visual.get("position", {}).get("height", 0) < 44:
                    issues.append(
                        f"{path.relative_to(ROOT)}: título executivo não tem altura "
                        "suficiente para o texto do cartão."
                    )
                if visual_definition.get("visualContainerObjects", {}).get("title"):
                    issues.append(
                        f"{path.relative_to(ROOT)}: título executivo não deve repetir "
                        "o nome técnico da medida."
                    )
        if visual_type == "slicer":
            slicer_mode = visual_definition.get("objects", {}).get("data", [])
            if not slicer_mode or slicer_mode[0].get("properties", {}).get(
                "mode", {}
            ).get("expr", {}).get("Literal", {}).get("Value") != "'Dropdown'":
                issues.append(
                    f"{path.relative_to(ROOT)}: segmentador deve usar apresentação "
                    "compacta em lista suspensa."
                )
        for kind, entity, prop in walk_field_refs(visual):
            if entity not in columns:
                issues.append(f"{path.relative_to(ROOT)}: tabela inexistente {entity}.")
            elif kind == "Column" and prop not in columns[entity]:
                issues.append(f"{path.relative_to(ROOT)}: coluna inexistente {entity}.{prop}.")
            elif kind == "Measure" and prop not in measures.get(entity, set()):
                issues.append(f"{path.relative_to(ROOT)}: medida inexistente {entity}.{prop}.")
        if visual_type in {
            "lineChart", "clusteredBarChart", "clusteredColumnChart",
            "lineClusteredColumnComboChart", "scatterChart", "waterfallChart", "treemap",
        }:
            axis_units = visual_definition.get("objects", {}).get("valueAxis", [])
            if axis_units and axis_units[0].get("properties", {}).get(
                "labelDisplayUnits", {}
            ).get("expr", {}).get("Literal", {}).get("Value") != "1D":
                issues.append(
                    f"{path.relative_to(ROOT)}: eixo deve exibir valores completos, "
                    "sem abreviação automática."
                )
            tooltips = visual.get("visual", {}).get(
                "visualContainerObjects", {}
            ).get("visualTooltip", [])
            if not any(
                item.get("properties", {}).get("section", {}).get("expr", {})
                .get("Literal", {}).get("Value") == "'tooltip_kpi'"
                for item in tooltips
            ):
                issues.append(f"Tooltip personalizado não associado: {path.relative_to(ROOT)}")
    return len(visual_paths)


def validate_csvs(issues: list[str]) -> dict[str, int]:
    import pandas as pd

    data_dir = ROOT / "dados"
    expected = [
        "fato_vendas", "dim_cliente", "dim_produto", "dim_vendedor",
        "dim_regiao", "dim_calendario", "meta_mensal", "dim_etapa_cascata",
    ]
    row_counts = {}
    frames = {}
    for table in expected:
        path = data_dir / f"{table}.csv"
        if not path.exists():
            issues.append(f"CSV ausente: {path.relative_to(ROOT)}")
            continue
        frame = pd.read_csv(path, encoding="utf-8")
        frames[table] = frame
        row_counts[table] = int(len(frame))
        if frame.empty:
            issues.append(f"CSV sem linhas: {path.relative_to(ROOT)}")
    if "fato_vendas" in frames:
        fact = frames["fato_vendas"]
        if not 49_000 <= len(fact) <= 50_075:
            issues.append(f"Fato fora da faixa esperada (~50 mil): {len(fact)} linhas.")
        if fact["id_item_venda"].duplicated().any():
            issues.append("id_item_venda não é único após limpeza.")
        checks = [
            ("id_cliente", "dim_cliente", "id_cliente"),
            ("id_produto", "dim_produto", "id_produto"),
            ("id_vendedor", "dim_vendedor", "id_vendedor"),
            ("id_regiao", "dim_regiao", "id_regiao"),
        ]
        for fact_col, dimension, key in checks:
            if dimension in frames and not fact[fact_col].isin(frames[dimension][key]).all():
                issues.append(f"Chaves órfãs em fato_vendas.{fact_col}.")
        if {"dim_vendedor", "meta_mensal"} <= frames.keys():
            delivered = fact.loc[fact["status"] == "Entregue"].copy()
            delivered["faturamento_linha"] = (
                delivered["quantidade"] * delivered["preco_unitario"]
                * (1 - delivered["desconto_pct"])
            )
            actual = delivered.groupby("id_vendedor")["faturamento_linha"].sum()
            targets = frames["meta_mensal"].groupby("id_vendedor")["valor_meta"].sum()
            attainment = actual.div(targets)
            if not (attainment > 1.15).any():
                issues.append("Nenhum vendedor está significativamente acima da meta.")
            if not (attainment < 0.80).any():
                issues.append("Nenhum vendedor está significativamente abaixo da meta.")
    if "dim_calendario" in frames and len(frames["dim_calendario"]) != 1_461:
        issues.append(
            f"Calendário deveria conter 1.461 dias (2023-2026): "
            f"{len(frames['dim_calendario'])}."
        )
    if "dim_calendario" in frames:
        calendar_dates = pd.to_datetime(frames["dim_calendario"]["data"])
        if calendar_dates.min().strftime("%Y-%m-%d") != "2023-01-01" or \
                calendar_dates.max().strftime("%Y-%m-%d") != "2026-12-31":
            issues.append("Calendário não cobre integralmente 2023-2026.")
    return row_counts


def validate_theme(issues: list[str]) -> None:
    report_path = ROOT / "VendasRentabilidade.Report" / "definition" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    registered_packages = {
        package.get("name"): package
        for package in report.get("resourcePackages", [])
        if package.get("type") == "RegisteredResources"
    }
    custom_theme = report.get("themeCollection", {}).get("customTheme")
    if custom_theme and not registered_packages:
        issues.append(
            "report.json declara um tema personalizado, mas não registra o pacote "
            "RegisteredResources."
        )
    if custom_theme:
        package = registered_packages.get(custom_theme.get("type"))
        if not package or not any(
            item.get("type") == "CustomTheme"
            for item in package.get("items", [])
        ):
            issues.append(
                "Tema personalizado em themeCollection não corresponde a um recurso "
                "CustomTheme registrado."
            )
    for package in report.get("resourcePackages", []):
        for item in package.get("items", []):
            package_folder = {
                "SharedResources": "SharedResources",
                "RegisteredResources": "RegisteredResources",
            }.get(package.get("type"), package.get("type", ""))
            resource_path = (
                ROOT / "VendasRentabilidade.Report" / "StaticResources"
                / package_folder / item["path"]
            )
            if not resource_path.is_file():
                issues.append(
                    f"Recurso PBIR ausente: {resource_path.relative_to(ROOT)} "
                    f"(referenciado por {package.get('name')})."
                )
    path = (
        ROOT / "VendasRentabilidade.Report" / "StaticResources"
        / "RegisteredResources" / "VendasRentabilidade.json"
    )
    if not path.is_file():
        issues.append(
            "Tema personalizado ausente: "
            f"{path.relative_to(ROOT)}."
        )
        return
    theme = json.loads(path.read_text(encoding="utf-8"))
    palette = theme.get("dataColors", [])
    if len(palette) != 6 or any(not re.fullmatch(r"#[0-9A-Fa-f]{6}", color) for color in palette):
        issues.append("Tema precisa ter exatamente seis cores hexadecimais válidas.")
    if theme.get("textClasses", {}).get("title", {}).get("fontFace") != "Segoe UI Semibold":
        issues.append("Tema não usa Segoe UI Semibold nos títulos.")
    callout = theme.get("textClasses", {}).get("callout", {})
    if callout.get("fontFace") != "Segoe UI Semibold" or callout.get("fontSize", 100) > 20:
        issues.append("Tema deve manter os valores dos cartões em Segoe UI Semibold até 20 pt.")
    fill_states = {
        state.get("$id"): state
        for state in theme.get("visualStyles", {})
        .get("pageNavigator", {}).get("*", {}).get("fill", [])
    }
    required_states = {"default", "hover", "selected", "disabled"}
    if set(fill_states) != required_states:
        issues.append(
            "Preenchimento do page navigator deve definir default, hover, selected e disabled."
        )
    for state_name in required_states:
        state = fill_states.get(state_name, {})
        if state.get("show") is not True or not state.get("fillColor"):
            issues.append(f"Preenchimento não está habilitado em todos os estados: {state_name}.")
    card_styles = theme.get("visualStyles", {}).get("card", {}).get("*", {})
    if not card_styles.get("border") or not card_styles.get("dropShadow"):
        issues.append("Tema de cartões deve definir borda arredondada e sombra.")
    callout_styles = card_styles.get("calloutValue", [])
    if not callout_styles or callout_styles[0].get("fontSize", 100) > 20:
        issues.append("Tema deve limitar valores de cartão a 20 pt para evitar truncamento.")
    shared_styles = theme.get("visualStyles", {}).get("*", {}).get("*", {})
    if shared_styles.get("valueAxis", [{}])[0].get("labelDisplayUnits") != 1:
        issues.append("Eixos numéricos devem exibir valores completos, sem abreviações automáticas.")
    if shared_styles.get("labels", [{}])[0].get("labelDisplayUnits") != 1:
        issues.append("Rótulos de dados devem exibir valores completos, sem abreviações automáticas.")
    navigator = theme.get("visualStyles", {}).get("pageNavigator", {}).get("*", {})
    if {state.get("$id") for state in navigator.get("fill", [])} != {
        "default", "hover", "selected", "disabled",
    }:
        issues.append("Tema deve definir o preenchimento dos quatro estados de navegação.")
    base_theme_path = (
        ROOT / "VendasRentabilidade.Report" / "StaticResources"
        / "SharedResources" / "BaseThemes" / "CY24SU06.json"
    )
    if not base_theme_path.exists():
        issues.append(f"Tema-base do relatório ausente: {base_theme_path.relative_to(ROOT)}")
    page_root = ROOT / "VendasRentabilidade.Report" / "definition" / "pages"
    for page_path in page_root.glob("*/page.json"):
        page = json.loads(page_path.read_text(encoding="utf-8"))
        if page.get("name") != "tooltip_kpi" and not page.get("objects", {}).get("background"):
            issues.append(f"Fundo personalizado ausente em {page_path.relative_to(ROOT)}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida CSVs, TMDL e PBIR.")
    parser.add_argument("--skip-schema-download", action="store_true",
                        help="Não consultar schemas oficiais; só funciona se estiverem em cache.")
    args = parser.parse_args()
    issues: list[str] = []

    schema_files = [
        (ROOT / "VendasRentabilidade.pbip", SCHEMA_URLS["pbip"]),
        (ROOT / "VendasRentabilidade.Report" / "definition.pbir", SCHEMA_URLS["pbir"]),
        (ROOT / "VendasRentabilidade.Report" / "definition" / "report.json", SCHEMA_URLS["report"]),
        (ROOT / "VendasRentabilidade.Report" / "definition" / "pages" / "pages.json", SCHEMA_URLS["pages"]),
        (ROOT / "VendasRentabilidade.Report" / "definition" / "version.json", SCHEMA_URLS["version"]),
        (
            ROOT / "VendasRentabilidade.Report" / "StaticResources" / "SharedResources"
            / "BaseThemes" / "CY24SU06.json",
            SCHEMA_URLS["theme"],
        ),
        (ROOT / "VendasRentabilidade.SemanticModel" / "definition.pbism", SCHEMA_URLS["semantic_model"]),
    ]
    custom_theme_path = (
        ROOT / "VendasRentabilidade.Report" / "StaticResources"
        / "RegisteredResources" / "VendasRentabilidade.json"
    )
    if custom_theme_path.is_file():
        schema_files.append((custom_theme_path, SCHEMA_URLS["theme"]))
    for page_path in sorted((ROOT / "VendasRentabilidade.Report" / "definition" / "pages").glob("*/page.json")):
        schema_files.append((page_path, SCHEMA_URLS["page"]))
    for visual_path in sorted((ROOT / "VendasRentabilidade.Report" / "definition" / "pages").glob("*/visuals/*/visual.json")):
        schema_files.append((visual_path, SCHEMA_URLS["visual"]))
    for path, schema_url in schema_files:
        if args.skip_schema_download and not (SCHEMA_CACHE / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', schema_url)}.json").exists():
            issues.append(f"Schema não está em cache para validação offline: {schema_url}")
            continue
        validate_json(path, schema_url, issues)

    columns, measures = validate_model(issues)
    visual_count = validate_report_fields(columns, measures, issues)
    rows = validate_csvs(issues)
    validate_theme(issues)

    if len(list((ROOT / "VendasRentabilidade.Report" / "definition" / "pages").glob("*/page.json"))) != 7:
        issues.append("O relatório não contém exatamente sete páginas.")
    pages_metadata_path = (
        ROOT / "VendasRentabilidade.Report" / "definition" / "pages" / "pages.json"
    )
    pages_metadata = json.loads(pages_metadata_path.read_text(encoding="utf-8"))
    if pages_metadata.get("activePageName") != "visao_executiva":
        issues.append("A página inicial do relatório deve ser a Visão Executiva.")
    drillthrough_path = (
        ROOT / "VendasRentabilidade.Report" / "definition" / "pages"
        / "detalhe_vendedor" / "page.json"
    )
    if drillthrough_path.is_file():
        drillthrough_page = json.loads(drillthrough_path.read_text(encoding="utf-8"))
        if drillthrough_page.get("visibility") != "HiddenInViewMode":
            issues.append(
                "Detalhe do Vendedor deve ficar oculto na navegação normal e ser "
                "acessado por drill-through."
            )
        drill_visuals = list(
            (drillthrough_path.parent / "visuals").glob("*/visual.json")
        )
        if any(
            json.loads(path.read_text(encoding="utf-8"))
            .get("visual", {}).get("visualType") == "pageNavigator"
            for path in drill_visuals
        ):
            issues.append("A página de drill-through não deve exibir pageNavigator.")
    quality_file = ROOT / "dados" / "relatorio_qualidade.json"
    if not quality_file.exists():
        issues.append("Relatório de qualidade ausente.")
    else:
        json.loads(quality_file.read_text(encoding="utf-8"))
    if issues:
        print("FALHAS DE VALIDAÇÃO:")
        for issue in issues:
            print(f"- {issue}")
        if COMPATIBILITY_NOTES:
            print("AVISOS DE COMPATIBILIDADE:")
            for note in sorted(COMPATIBILITY_NOTES):
                print(f"- {note}")
        return 1
    print("Validação concluída sem falhas.")
    print(f"Tabelas: {len(columns)}; medidas: {sum(map(len, measures.values()))}; visuais: {visual_count}")
    print(f"Linhas CSV: {json.dumps(rows, ensure_ascii=False, sort_keys=True)}")
    print(f"Schemas oficiais em cache: {SCHEMA_CACHE}")
    if COMPATIBILITY_NOTES:
        print("AVISOS DE COMPATIBILIDADE:")
        for note in sorted(COMPATIBILITY_NOTES):
            print(f"- {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
