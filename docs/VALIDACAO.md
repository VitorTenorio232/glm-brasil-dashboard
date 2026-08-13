# Estratégia de validação

A validação do pacote é dividida em três níveis.

1. **Sintaxe e testes unitários**: transição GOES-16/19, parsing de nomes e fórmulas de anomalia.
2. **Simulação reproduzível**: cria 48 arquivos NetCDF GLM sintéticos, dois anos, 12 meses e três municípios; executa leitura, QC opcional, spatial join e todos os produtos V1–V3.
3. **Validação operacional externa**: requer rede para NOAA/AWS e credenciais do Earth Engine. O ambiente de geração do pacote não possui acesso direto a esses serviços, então essa etapa deve ser executada no computador/servidor do projeto usando os comandos do README.

O arquivo `data/demo/SIMULATION_REPORT.md` registra o resultado real da simulação executada durante a construção do pacote.
