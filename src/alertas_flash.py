"""Alertas OBSERVACIONAIS GLM e legenda retrátil para o Flash View.

Não se trata de previsão de raios nem de alerta oficial. A classe descreve
atividade detectada no recorte selecionado e a sua tendência recente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import math

import pandas as pd


@dataclass(frozen=True)
class LightningActivity:
    latest_10min: int
    previous_10min: int
    older_10min: int
    trend: str
    delta_percent: float | None
    status: str
    stale: bool


def analyze_glm_activity(flashes: pd.DataFrame, observation_end: datetime,
                         latency_minutes: float, *, min_count_for_trend: int = 5,
                         max_latency_minutes: float = 10.0) -> LightningActivity:
    """Conta flashes em janelas iguais 0-10, 10-20, 20-30 min.

    Ancoragem é o fim da última observação, evitando extrapolação temporal.
    A tendência é descritiva, não preditiva. Limiares exploratórios.
    """
    obs = pd.Timestamp(observation_end)
    if obs.tzinfo is None:
        obs = obs.tz_localize('UTC')
    else:
        obs = obs.tz_convert('UTC')

    if flashes is None or flashes.empty or 'time_start' not in flashes:
        counts = [0, 0, 0]
    else:
        ts = pd.to_datetime(flashes['time_start'], utc=True, errors='coerce')
        age = (obs - ts).dt.total_seconds() / 60.0
        counts = [int(((age >= lo) & (age < hi)).sum()) for lo, hi in [(0,10),(10,20),(20,30)]]

    current, previous, older = counts
    stale = not math.isfinite(float(latency_minutes)) or latency_minutes > max_latency_minutes
    if stale:
        return LightningActivity(current, previous, older, 'Indisponível', None,
                                 'Dados desatualizados', True)
    if current == 0 and previous == 0:
        return LightningActivity(current, previous, older, 'Sem atividade recente', None,
                                 'Sem flashes nos últimos 20 min', False)
    if current + previous < min_count_for_trend:
        trend = 'Amostra pequena'
    elif previous == 0:
        trend = 'Atividade iniciada'
    elif current >= previous * 1.5 and current - previous >= 3:
        trend = 'Intensificação ▲'
    elif current <= previous * 0.67 and previous - current >= 3:
        trend = 'Redução ▼'
    else:
        trend = 'Relativamente estável ▬'
    delta = ((current - previous) / previous * 100) if previous > 0 else None
    status = ('Flashes detectados nos últimos 10 min' if current else
              'Sem flashes nos últimos 10 min')
    return LightningActivity(current, previous, older, trend, delta, status, False)


def render_observational_alert(st, summary: LightningActivity) -> None:
    """UI leve, sem notificação externa ou falsas classes de severidade."""
    with st.container(border=True):
        st.markdown('**⚡ Monitoramento de atividade elétrica — GLM**')
        c1, c2, c3 = st.columns(3)
        c1.metric('Flashes · últimos 10 min', f'{summary.latest_10min:,}'.replace(',', '.'))
        c2.metric('Flashes · 10–20 min', f'{summary.previous_10min:,}'.replace(',', '.'))
        c3.metric('Tendência observada', summary.trend)
        if summary.stale:
            st.warning('Dados GLM desatualizados. Não é possível avaliar a atividade atual com segurança.')
        elif summary.latest_10min:
            st.warning(f'**Aviso observacional:** {summary.status.lower()} no recorte mostrado.')
        else:
            st.info(summary.status + ' no recorte mostrado.')
        st.caption('Indicador experimental, baseado em contagens em intervalos iguais de 10 min. '
                   'Não representa probabilidade de raio, previsão nem aviso oficial. '
                   'O GLM inclui relâmpagos intranuvem e nuvem-solo.')


def add_collapsible_glm_legend(mapa, age_groups) -> None:
    """Adiciona legenda recolhível ao Folium, mantendo as faixas atuais do GLM."""
    from branca.element import Element
    spans = ''.join(
        '<div class="fv-legend-item"><i style="background:%s"></i>%s</div>' %
        (escape(str(color)), escape(str(label)))
        for label, _lo, _hi, color in age_groups
    )
    markup = '''<style>
    .fv-glm-legend {position:fixed;bottom:24px;left:20px;z-index:9999;
       background:rgba(13,23,39,.95);color:#f8fafc;border:1px solid rgba(255,255,255,.16);
       border-radius:12px;box-shadow:0 5px 25px rgba(0,0,0,.33);font:13px Arial,sans-serif;
       overflow:hidden;min-width:172px;max-width:240px;}
    .fv-glm-legend summary {cursor:pointer;padding:11px 14px;font-weight:700;user-select:none;}
    .fv-glm-legend .fv-legend-body {padding:0 14px 12px;}
    .fv-legend-item {display:flex;align-items:center;gap:9px;padding:3px 0;}
    .fv-legend-item i {width:11px;height:11px;border:1px solid rgba(255,255,255,.5);
          border-radius:50%;display:inline-block;flex-shrink:0;}
    .fv-glm-legend small {display:block;margin-top:7px;color:#cbd5e1;line-height:1.3;}
    @media (max-width: 700px) {.fv-glm-legend {left:9px;bottom:9px;}}
    </style>
    <details id="fv-glm-legend" class="fv-glm-legend" open>
       <summary>⚡ Intervalo dos Flashes</summary>
       <div class="fv-legend-body">''' + spans + '''
       <small>Ao vivo: 30 min; animação: quadros de 5 min (1 h)</small></div></details>
    <script>
    (function(){
      var el=document.getElementById('fv-glm-legend'); if(!el)return;
      try {var key='fv-glm-legend-open'; var v=sessionStorage.getItem(key);
           el.open = v === null ? window.innerWidth >= 700 : v === '1';
           el.addEventListener('toggle',function(){sessionStorage.setItem(key,el.open?'1':'0');});
      } catch(e) {el.open = window.innerWidth >= 700;}
    })();
    </script>'''
    mapa.get_root().html.add_child(Element(markup))
