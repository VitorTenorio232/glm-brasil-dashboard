# Relatório de validação — GLM Brasil V4

Data da validação: 2026-08-11

## Escopo validado

A V4 foi construída a partir da V3 e mantém os módulos de download/leitura GLM, QC, associação municipal e persistência. O frontend foi substituído pelo fluxo **Área → Período → Análises**.

## Testes automatizados

Resultado final:

```text
10 passed
```

Os testes incluem os 6 testes herdados da V3 e 4 testes novos do V4:

- leitura da base individual e filtro municipal;
- climatologia/profile municipal com 12 meses;
- rankings estadual e municipal;
- filtro de região personalizada por ponto-em-polígono.

## Compilação

```text
python -m compileall -q app.py src scripts pages tests
COMPILE_OK
```

## Simulação V4 com os dados demo

Município Alpha:

```text
Flashes com horário válido: 1633
Linhas diárias: 711
Linhas mensais: 24
Linhas anuais: 2
Meses na climatologia: 12
Mês climatologicamente mais ativo: Janeiro (111,0 flashes/mês)
Mês climatologicamente menos ativo: Julho (24,5 flashes/mês)
```

Divisão diurno/noturno demo em UTC-3:

```text
Diurno: 822 flashes (50,34%)
Noturno: 811 flashes (49,66%)
```

Região personalizada sintética cobrindo dois municípios:

```text
Flashes: 4185
Ranking estadual: gerado
Ranking municipal: 2 municípios
```

## Mapas

Foram gerados com sucesso:

- mapa de satélite de seleção municipal;
- camada de limite da seleção;
- pontos por intervalos 0–5 / 5–10 / 10–15 min;
- mapa de desenho com ferramenta de polígono/retângulo.

Arquivos demo:

```text
data/demo/v4_map_city.html
data/demo/v4_draw_map.html
```

## Migração

O script `glm_v4_patch/apply_v4.sh` foi aplicado sobre uma cópia limpa do pacote V3. Após a migração, os 10 testes passaram e todo o código compilou.

## Limites da validação

O ambiente usado para montar o pacote não possui Streamlit instalado, portanto a renderização completa da aplicação Streamlit não foi iniciada neste ambiente. Os módulos de cálculo, consulta, geometria e geração Folium foram executados diretamente. No computador do projeto, onde Streamlit/streamlit-folium já estão instalados, a execução final deve ser feita com `python -m streamlit run app.py`.

O teste com a base GLM real já havia sido executado pelo usuário na V3, com 6.134 flashes lidos e 1.545 associados a municípios. A V4 reutiliza esse backend e passa a depender de `flashes_enriched.parquet` (`--save-flashes`) para análises dinâmicas.
