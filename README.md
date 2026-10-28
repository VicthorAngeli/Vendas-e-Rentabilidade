# Vendas e Rentabilidade — Power BI PBIP

Projeto sintético de distribuidora brasileira para Power BI Desktop, construído em
PBIP com relatório PBIR e modelo semântico TMDL.

## Abrir

1. Abra `VendasRentabilidade.pbip` no Power BI Desktop atualizado.
2. Na primeira abertura, aguarde a carga dos CSVs em `dados`.
3. Use as abas do relatório para navegar entre as sete páginas.

O Power BI Desktop está instalado no ambiente de desenvolvimento. A validação
estrutural não substitui a conferência das interações finais no Desktop.

## Regenerar dados

Python 3.10+ é recomendado. Na raiz do projeto:

```powershell
python -m pip install pandas Faker jsonschema
python scripts\gerar_dados.py
python scripts\tratar_dados.py
python scripts\gerar_projeto.py
python scripts\validar.py
```

`gerar_dados.py` grava dados brutos em `dados\brutos`; `tratar_dados.py` produz os
CSVs limpos diretamente em `dados` e `relatorio_qualidade.json`. A semente fixa é
`20261027`. Clientes com nomes semelhantes são mantidos quando têm IDs distintos;
duplicatas de fato são removidas por `id_item_venda`, nunca pelo nome.

## Trocar a pasta de dados

O caminho é um parâmetro de Power Query chamado `PastaDados`, definido em
`VendasRentabilidade.SemanticModel\definition\expressions.tmdl`. Por segurança, o
projeto versionado usa o caminho genérico `C:\PowerBI\VendasRentabilidade\dados`, não
um caminho pessoal. Antes de atualizar os dados no Power BI Desktop, altere o
parâmetro em Transformar dados / Gerenciar parâmetros para a pasta `dados` deste
clone. Os CSVs devem conservar os nomes e cabeçalhos gerados pelo pipeline.

## Modelo

- Esquema estrela com `fato_vendas` e dimensões de cliente, produto, vendedor,
  região e calendário; `meta_mensal` relaciona-se ao vendedor e recebe o contexto
  mensal por `TREATAS` para não criar uma relação diária ambígua.
- Relações many-to-one ativas e unidirecionais; chaves técnicas ficam ocultas.
- `dim_calendario` é a tabela de datas e `model.tmdl` usa cultura `pt-BR`.
  Como os CSVs exportam decimais com ponto, as consultas os interpretam com
  `en-US`; isso evita que preços e percentuais sejam lidos como milhares.
- Medidas ficam em `_Medidas` e organizadas por pasta de exibição. Os textos
  documentais ficam como comentários TMDL para compatibilidade com a versão atual
  do Desktop; eles não são descrições semânticas visíveis nas propriedades das
  medidas.
- O pipeline gera 50.000 linhas de venda antes da inclusão de 75 cópias controladas;
  os CSVs limpos ficam em torno de 50 mil linhas.
- A fato não utiliza dados reais. Metas, sazonalidade, taxas e preços são sintéticos.

## Relatório

Páginas incluídas: Visão Executiva, Vendas por Produto, Clientes, Equipe Comercial,
Rentabilidade, Detalhe do Vendedor (drill-through) e Tooltip - Mini KPIs. As páginas
analíticas usam `pageNavigator` para navegação; a página de drill-through fica oculta
na navegação normal, e a página de tooltip contém mini-KPIs
e está associada aos gráficos de linha, barra, cascata e treemap. Os KPIs
executivos exibem valores monetários completos, sem escala automática em milhares ou
milhões; os eixos e rótulos numéricos também evitam abreviações automáticas. A página
de clientes usa medidas que limitam faturamento e ticket médio aos dez clientes mais
bem ranqueados no contexto selecionado.
O layout usa canvas 16:9 (1280×720), fundo azul-claro, cartões brancos com bordas
suaves, títulos/KPIs em Segoe UI e paleta acessível de seis cores. As páginas usam
o mesmo grid, com KPIs no topo, gráficos centrais e filtros agrupados. A página de
produtos usa barras por categoria, treemap por categoria/subcategoria e matriz com
classificação ABC para manter os visuais legíveis. Os dados suportam detalhamento
por vendedor, cliente, categoria, região, mês e canal.

## Qualidade e validação

`relatorio_qualidade.json` registra linhas de entrada/saída, remoções por chave,
duplicatas retiradas, valores ND convertidos e nulos imputados. `validar.py` valida
os arquivos PBIR/PBIP/PBISM contra os schemas públicos Microsoft versionados no
projeto, confere campos usados nos visuais, duplicidade de GUIDs, relações, chaves,
medidas versus colunas, dados e tema. A primeira execução precisa de internet para
baixar os schemas; as cópias ficam em `scripts\schemas`.

Schemas consultados (repositório oficial Microsoft `json-schemas`, branch `main`):

- PBIP shortcut 1.0.0; PBIR definition properties 2.0.0.
- Report 3.3.0; page 2.1.0; pages metadata 1.1.0; version metadata 1.0.0.
- Visual container 2.13.0; semantic model definition properties 1.0.0.
- Tema de relatório 2.159 do repositório de amostras Microsoft.
- [PBIP overview](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- [Report PBIR structure](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)
- [Semantic model and TMDL structure](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)
- [TMDL language](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- [Dashboard design guidance](https://learn.microsoft.com/en-us/power-bi/create-reports/service-dashboards-design-tips)
- [Accessibility guidance](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-accessibility-creating-reports)

- O semáforo é textual ("Acima da meta", "Atenção", "Abaixo da meta") para não
  depender apenas de cor; o comportamento de formatação condicional por valor não
  foi aplicado.
