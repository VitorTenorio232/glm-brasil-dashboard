# Relatório de validação — Dashboard GLM Brasil V3

Data da validação: 11/08/2026.

## 1. Validação local executada

O pacote foi validado com uma simulação reproduzível que cria arquivos NetCDF com a mesma estrutura lógica das variáveis de flash usadas pelo pipeline (`flash_lat`, `flash_lon`, horários inicial/final, área, energia e flag de qualidade).

Resultado da rodada final:

- 48 arquivos NetCDF GLM sintéticos;
- 6.102 flashes brutos;
- 5.658 flashes após o filtro opcional `flash_quality_flag == 0`;
- 5.334 flashes atribuídos a municípios;
- 3 municípios sintéticos;
- 2 anos × 12 meses;
- climatologia mensal, anual, anomalias, z-score, ciclo diurno, recordes, energia, área e duração gerados.

O simulador foi alterado para declarar `flash_area` em **square meters**, validando também a conversão automática para km² usada internamente.

## 2. Testes automatizados

Comando:

```bash
python -m compileall -q app.py src scripts pages tests
pytest -q
```

Resultado final:

```text
6 passed
```

Cobertura funcional dos testes incluídos:

- transição GOES-16 → GOES-19;
- parsing do timestamp em nomes LCFA;
- cálculo de anomalias;
- conversão m² → km² de `flash_area`;
- existência/consistência das saídas demo.

## 3. Teste do pipeline operacional sobre NetCDF

Foi executado o mesmo `scripts/process_glm.py` utilizado no fluxo real sobre os 48 NetCDFs sintéticos. Foram geradas sem erro as saídas:

```text
daily
monthly
annual
hourly
diurnal
monthly_climatology
annual_climatology
monthly_anomalies
records
completeness_daily
completeness_monthly
quality_summary
```

Também foi gerado `data/demo/demo_map.html` usando a tabela mensal e a malha municipal de teste.

## 4. O que não pôde ser validado neste ambiente

### NOAA/AWS

A tentativa de conexão direta ao bucket público falhou por indisponibilidade de resolução DNS/rede no ambiente isolado de construção. Portanto, o downloader foi validado por testes de parsing/seleção de satélite e pelo pipeline sintético, mas **a transferência externa real precisa ser testada na máquina que executará o projeto**.

Use:

```bash
python scripts/check_external_services.py --time 2025-11-13T03:00:00Z
```

### Google Earth Engine

A renderização autenticada não foi executada neste ambiente porque não há credenciais do projeto Earth Engine. O dashboard possui fallback Folium local e o módulo Earth Engine foi incluído para produção.

Após autenticar, teste:

```bash
earthengine authenticate
python scripts/check_external_services.py --ee-project SEU_PROJETO
```

## 5. Conclusão

A lógica V1–V3 e o fluxo local completo foram aprovados. A etapa restante antes de chamar a instalação de "produção validada" é um teste externo curto com arquivos GLM reais e o Asset municipal real do Earth Engine no ambiente onde o dashboard será publicado.
