# Alarme de relâmpagos

Há duas formas de ser avisado quando cai relâmpago na sua área de observação:

- **no site**, com o botão **🔔 Ativar alarme** do mapa ao vivo (seção abaixo). Não precisa instalar nada, mas
  a aba do site precisa ficar aberta;
- **no computador**, com o `scripts/alarme_relampagos.py` (seções 1 a 5). Roda fora do navegador e também
  avisa o celular pelo ntfy.

Os dois usam a mesma regra: tocam quando há relâmpago na área nos últimos 10 min e só tocam de novo depois de
30 min sem relâmpagos na área.

## No site: botão "Ativar alarme"

1. Na aba **Relâmpagos em tempo real**, escolha a área na barra **Área no mapa** (os mesmos tipos da Tendência):
   - **Pontual:** clique no mapa (ou digite as coordenadas, ou escolha um município) e ajuste o raio;
   - **Retângulo:** arraste no mapa para desenhar (ou clique em dois cantos opostos), ou digite os limites;
   - **Estados** ou **Municípios:** escolha um ou mais na lista;
   - **Arquivo:** envie um shapefile (ZIP), KML, KMZ ou GeoJSON.
2. Clique em **🔊 Testar som** no canto do mapa para ouvir a sirene e acertar o volume.
3. Clique em **🔔 Ativar alarme**. Dois bipes curtos confirmam que o som foi liberado. Se o navegador pedir
   permissão para notificações, aceite: assim o aviso aparece mesmo com o navegador minimizado.

Quando cai relâmpago na área, o site:

- toca uma sirene em loop;
- cobre a tela com um aviso vermelho que mostra a distância e a direção do relâmpago mais perto (a partir do
  ponto, no modo Pontual, ou do centro da área), quantos caíram nos últimos 10 min e o horário do último;
- faz o título da aba piscar e, se você permitiu, mostra uma notificação do sistema;
- no celular Android, também vibra.

O som continua até você clicar em **Parar alarme**. Se ninguém clicar, para sozinho depois de 10 min e o aviso
fica na tela. Enquanto o alarme está ativo, a tela fica acesa (o navegador não deixa o aparelho dormir).

**Para funcionar a noite toda:**

- deixe a aba do site **aberta e visível**: pode ser numa janela só dela, mas não minimize nem troque de aba do
  navegador por muito tempo, porque Chrome e Edge podem pôr abas de fundo para dormir;
- não troque de aba dentro do site nem recarregue a página: o alarme desliga e precisa ser ativado de novo
  (o navegador exige um clique para liberar o som);
- deixe o volume alto e o computador ligado. No celular, o modo silencioso do iPhone pode calar o som do site.

Se o site parar de receber dados (internet, servidor ou atraso da NOAA), o painel do alarme mostra um aviso ⚠️
e, se você permitiu, sai uma notificação.

## No computador: `scripts/alarme_relampagos.py`

O script roda no seu computador, fora do navegador.

- A cada minuto, busca na NOAA/AWS os arquivos novos do GLM (GOES-19). Cada arquivo cobre 20 s e o script só
  baixa os que ainda não leu.
- Quando há relâmpago dentro da área, abre uma **janela vermelha, sempre por cima, com som de despertador em
  loop**, até você clicar em **Parar alarme**. Se ninguém clicar, o som para sozinho depois de 10 min e a
  janela fica aberta mostrando o que aconteceu.
- Se você configurar, manda também um **aviso urgente para o celular** pelo app gratuito **ntfy** (Android ou
  iPhone).
- Toca **uma vez por tempestade**. Só volta a tocar depois de 30 min sem relâmpagos na área, para não disparar
  a cada minuto durante a mesma chuva.
- Enquanto roda, impede o Windows de suspender (a tela pode apagar normalmente) e avisa se os dados pararem de
  chegar, porque nesse caso o alarme fica cego.

> **Dado observacional, não é alerta oficial.** Para decisões de segurança, siga a Defesa Civil e o INMET.

### 1. Configurar a área

Na pasta do repositório, copie `alarme.exemplo.toml` para `alarme.toml` e ajuste a seção `[area]`. O
`alarme.toml` fica fora do Git, porque guarda a sua localização e o tópico do celular.

```toml
[area]
nome = "Minha casa"
lat = -22.4136      # no Google Maps: botão direito no lugar e clique nos números para copiar
lon = -45.4497
raio_km = 20
```

Para usar um polígono no lugar do raio, informe `arquivo = "minha_area.kml"`, que aceita KML, KMZ, GeoJSON ou
SHP em ZIP (os mesmos formatos da opção **Arquivo** do site). Nesse caso `lat` e `lon` viram só o ponto de
referência para a distância nas mensagens.

**Que raio usar?** O GLM localiza cada relâmpago com erro de alguns quilômetros (pixel de ~8 a 14 km no
Brasil), então use pelo menos 10 km. Para ser acordado quando a tempestade *chega*, 20 a 30 km dá alguns
minutos de antecedência. Com 10 km, o alarme toca quando ela já está perto.

### 2. Testar

```bash
python scripts/alarme_relampagos.py --testar
```

Esse comando abre a janela com som e, se o celular estiver ativo, manda um aviso de teste. Use-o para conferir
o volume do PC e a notificação do celular.

Para ver se a área está certa sem tocar nada, use `--uma-vez`. Ele olha os últimos 10 min, mostra quantos
relâmpagos caíram na área e sai.

```bash
python scripts/alarme_relampagos.py --uma-vez
```

### 3. Deixar rodando à noite

```bash
python scripts/alarme_relampagos.py
```

Você também pode dar dois cliques em `scripts\alarme_relampagos.bat`. Deixe a janela preta aberta: a cada
minuto ela mostra uma linha com a hora dos dados, o atraso e quantos relâmpagos caíram na área. Para parar,
feche a janela ou aperte Ctrl+C.

Para o alarme funcionar:

- o PC precisa ficar **ligado** (o script impede a suspensão automática, mas não a suspensão manual nem a de
  fechar a tampa do notebook);
- o **volume** precisa estar ligado e audível, e os alto-falantes ou fones conectados;
- a **internet** precisa estar funcionando.

### 4. Aviso no celular (ntfy)

O ntfy é um app gratuito de notificações e não pede cadastro. O PC manda a mensagem para um **tópico**, e o
celular inscrito nesse tópico recebe.

1. Instale o **ntfy** no celular (Play Store, F-Droid ou App Store).
2. Invente um nome de tópico longo e difícil de adivinhar, no formato `flashview-alarme-` seguido de letras e
   números aleatórios. Não copie o exemplo abaixo: o tópico funciona como senha, e quem souber o nome recebe os
   seus avisos.
3. No app, toque em **+**, digite o tópico e mantenha o servidor `ntfy.sh`.
4. No `alarme.toml`:

   ```toml
   [celular]
   ativo = true
   ntfy_topico = "flashview-alarme-xxxxxxxx"   # troque pelo seu
   ```

5. Rode `--testar` e confira se o aviso chegou.

**Para acordar com o celular no silencioso:** os avisos saem com prioridade **urgente** (a máxima do ntfy).

- **Android:** nas configurações de notificação do ntfy, permita que as notificações de prioridade máxima
  ignorem o **Não perturbe**. Se a sua versão tiver a opção de manter o som tocando até abrir a notificação,
  ative-a.
- **iPhone:** permita as notificações do ntfy e as **notificações sensíveis ao tempo** no modo Foco.

Cada aviso leva para o servidor do ntfy o nome da área, a distância, a direção e o horário. Por isso, não
coloque o seu endereço no `nome` da área.

### 5. Ajustes no `alarme.toml`

| Chave | Padrão | O que faz |
|---|---|---|
| `alarme.min_relampagos` | 1 | Quantos relâmpagos na área, dentro da janela, fazem tocar. Use 2 ou 3 para evitar alarme por um flash isolado. |
| `alarme.janela_min` | 10 | Janela de contagem, em minutos. |
| `alarme.rearmar_min` | 30 | Depois de tocar, quanto tempo sem relâmpagos na área até poder tocar de novo. |
| `alarme.intervalo_s` | 60 | De quanto em quanto tempo procurar dados novos (mínimo 15 s). |
| `alarme.qualidade` | `zero_only` | Só flashes com flag de qualidade 0, como no site; `all` usa todos. |
| `alarme.aviso_sem_dados_min` | 10 | Avisa se os dados pararem de chegar por esse tempo. |
| `computador.ativo` / `som` | true / true | Janela de alarme e som no PC. |
| `computador.duracao_max_min` | 10 | O som para sozinho depois disso, se ninguém clicar. |
| `computador.arquivo_som` | (bipes) | Um WAV seu no lugar dos bipes. |
| `celular.ativo` / `ntfy_topico` | false / vazio | Aviso no celular pelo ntfy. |
| `celular.prioridade` | `urgent` | Prioridade no ntfy (`default`, `high`, `urgent`). |

Também dá para rodar sem `alarme.toml` passando a área na linha de comando:

```bash
python scripts/alarme_relampagos.py --lat -22.41 --lon -45.45 --raio 20
```

## Limites

- **Atraso:** no teste de 07/11/2026, os arquivos chegaram à NOAA de 15 a 40 s depois do fim de cada janela de
  20 s. Somando a busca a cada minuto, o alarme toca de 1 a 2 min depois do relâmpago. Quando a NOAA atrasa, a
  demora pode chegar a vários minutos.
- **Detecção:** o GLM não vê todos os relâmpagos (a eficiência é menor de dia). Um flash isolado pode passar,
  mas uma tempestade costuma produzir muitos.
- **Tipo:** o GLM não separa intranuvem de nuvem-solo nem a polaridade. O alarme conta o total. Relâmpago
  intranuvem perto também indica tempestade sobre você.
- **Internet (alarme do computador):** cada arquivo tem ~370 KB, ou seja, ~65 MB por hora e ~1,6 GB por dia
  ligado. O alarme do site não baixa esses arquivos: quem busca é o servidor do site.
- **Registro (alarme do computador):** tudo o que o alarme faz fica em `%LOCALAPPDATA%\FlashView\alarme.log`.
