"""Flash View — seletor de área PARA A PRANCHA, independente do mapa interativo.

Somente usa geometrias EPSG:4326. Não lê NetCDF nem altera os cálculos científicos.
Países vêm de Natural Earth (arquivo estático, domínio público).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
import hashlib
import json

import numpy as np
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

DATAFILE = Path(__file__).resolve().parents[1] / 'data' / 'admin' / 'world_countries_110m.geojson'

@dataclass(frozen=True)
class ExportArea:
    label: str
    geometry: Optional[BaseGeometry]
    kind: str = 'aplicada'

    @property
    def signature(self):
        raw = self.geometry.wkb if self.geometry is not None else b'no-geometry'
        return hashlib.sha256(self.label.encode('utf-8') + b'|' + raw).hexdigest()[:16]


def valid_polygon(geom: BaseGeometry) -> BaseGeometry:
    """Rejeita geometria vazia/inválida; nunca ajusta dados silenciosamente."""
    if geom is None or geom.is_empty:
        raise ValueError('Área vazia. Selecione uma geometria válida.')
    if not geom.is_valid:
        raise ValueError(f'Geometria inválida: {explain_validity(geom)}')
    if geom.geom_type not in {'Polygon', 'MultiPolygon'}:
        raise ValueError('A área precisa ser um polígono, multipolígono, retângulo ou círculo.')
    w,s,e,n = geom.bounds
    if not all(np.isfinite([w,s,e,n])) or not -180 <= w < e <= 180 or not -85 < s < n < 85:
        raise ValueError('A geometria excede os limites suportados pela projeção Web Mercator (±85°).')
    return geom


def rectangle(south, west, north, east):
    try:
        south, west, north, east = map(float, (south, west, north, east))
    except (TypeError, ValueError) as err:
        raise ValueError('Informe quatro coordenadas válidas.') from err
    if not (-85 < south < north < 85 and -180 <= west < east <= 180):
        raise ValueError('Use sul < norte e oeste < leste, dentro dos limites geográficos.')
    return box(west, south, east, north)


@lru_cache(maxsize=1)
def countries(path: str | Path | None = None):
    """Países estáticos 110m. Sem chamadas a serviços externos durante a sessão."""
    p = Path(path) if path else DATAFILE
    raw = json.loads(p.read_text(encoding='utf-8'))
    return {f['properties']['name']: shape(f['geometry'])
            for f in raw['features'] if f.get('geometry')}


def country_names(path=None):
    names=list(countries(path))
    names.sort(key=lambda s: (s!='Brazil', s.casefold()))
    return names


def supported_country(name, path=None):
    try:
        geom=countries(path)[name]
    except KeyError as exc:
        raise ValueError(f'País não disponível: {name}') from exc
    return valid_polygon(geom)


def masked_raster_coverage(lat, lon, field, geom: BaseGeometry):
    """Conta pixels FINITOS do campo original na nova área, sem recalcular o produto."""
    from shapely import contains_xy
    lat=np.asarray(lat,dtype=float); lon=np.asarray(lon,dtype=float)
    field=np.ma.filled(np.ma.asarray(field,dtype=float),np.nan)
    if lat.ndim!=1 or lon.ndim!=1 or field.shape!=(len(lat),len(lon)):
        raise ValueError('Campo e coordenadas incompatíveis.')
    X,Y=np.meshgrid(lon,lat)
    return int(np.count_nonzero(np.isfinite(field)&contains_xy(geom,X,Y)))


def _safe_wkb(val):
    if not val:return None
    from shapely import from_wkb
    return valid_polygon(from_wkb(bytes.fromhex(val)))


def export_area_selector(*, prefix: str, applied_geom=None, applied_label='Área do mapa',
                         show_uploaded=True) -> Optional[ExportArea]:
    """UI Streamlit — inclui país, UF, município, retângulo e ponto/círculo.

    Retorna None se o usuário ainda não tiver desenhado/selecionado uma área.
    Não modifica estado de nenhum widget após sua criação.
    """
    import streamlit as st
    from src.historical_glm import load_states, load_municipalities, get_municipality_geometry, get_state_geometry
    from src.spatial_tools import circular_buffer_geometry, build_rectangle_selector_map, geometry_from_geojson
    from streamlit_folium import st_folium

    choices=['Área aplicada ao mapa', 'País', 'Estado brasileiro', 'Município brasileiro',
             'Retângulo', 'Ponto com círculo']
    if show_uploaded and st.session_state.get('fv_user_polygon_wkb'):
        choices.append('Polígono importado (SHP/KMZ)')

    with st.container(border=True):
        st.markdown('**🗺️ Selecionar área da imagem exportada**')
        kind=st.selectbox('Tipo de área', choices, key=f'{prefix}_export_area_type')

        try:
            if kind == 'Área aplicada ao mapa':
                if applied_geom is not None:
                    valid_polygon(applied_geom)
                st.caption(f'Usar recorte da última visualização: {applied_label}.')
                return ExportArea(applied_label, applied_geom, 'aplicada')

            if kind == 'País':
                opts=country_names()
                chosen=st.selectbox('País',opts,index=0,key=f'{prefix}_export_country',
                     format_func=lambda x: 'Brasil' if x=='Brazil' else x)
                geom=supported_country(chosen)
                label='Brasil' if chosen=='Brazil' else chosen
                if chosen=='Brazil':
                    # Preferir malha brasileira já disponível no projeto.
                    # Se indisponível, usar Natural Earth estático, sem bloquear a exportação.
                    try:
                        from src.historical_glm import load_country
                        geom=valid_polygon(load_country(2022))
                    except Exception:
                        st.caption('Utilizando contorno simplificado Natural Earth para o Brasil.')
                else:
                    st.caption('Contorno cartográfico simplificado Natural Earth 1:110m.')
                return ExportArea(label,geom,'pais')

            if kind == 'Estado brasileiro':
                states=load_states(2022)
                options={f'{r.abbrev_state} — {r.name_state}':str(r.abbrev_state) for r in states.itertuples()}
                name=st.selectbox('Estado',list(options),key=f'{prefix}_export_state')
                return ExportArea(name,valid_polygon(get_state_geometry(options[name],2022)),'estado')

            if kind == 'Município brasileiro':
                states=load_states(2022)
                options={f'{r.abbrev_state} — {r.name_state}':str(r.abbrev_state) for r in states.itertuples()}
                c1,c2=st.columns([.8,1.2])
                with c1:
                    name=st.selectbox('Estado',list(options),key=f'{prefix}_export_muni_uf')
                uf=options[name]
                munis=load_municipalities(uf,2022)
                lookup={f'{r.name_muni} ({uf})':str(r.code_muni) for r in munis.itertuples()}
                with c2:
                    municipio=st.selectbox('Município',list(lookup),key=f'{prefix}_export_municipality')
                return ExportArea(municipio,valid_polygon(get_municipality_geometry(lookup[municipio],uf,2022)),'municipio')

            if kind == 'Retângulo':
                mode=st.radio('Definir retângulo', ['Digitar coordenadas','Desenhar no mapa'],
                    horizontal=True, key=f'{prefix}_export_rectangle_method')
                if mode == 'Digitar coordenadas':
                    a,b,c,d=st.columns(4)
                    with a:south=st.number_input('Latitude sul', min_value=-84.9,max_value=84.9,value=-24.0,step=.1,key=f'{prefix}_exp_rect_s')
                    with b:north=st.number_input('Latitude norte',min_value=-84.9,max_value=84.9,value=-18.0,step=.1,key=f'{prefix}_exp_rect_n')
                    with c:west=st.number_input('Longitude oeste',min_value=-180.,max_value=180.,value=-49.0,step=.1,key=f'{prefix}_exp_rect_w')
                    with d:east=st.number_input('Longitude leste',min_value=-180.,max_value=180.,value=-42.0,step=.1,key=f'{prefix}_exp_rect_e')
                    geom=rectangle(south,west,north,east)
                    return ExportArea(f'Retângulo {south:.2f}°, {west:.2f}° a {north:.2f}°, {east:.2f}°',geom,'retangulo')
                # Reaproveita o seletor original de retângulo.
                stored_key=f'{prefix}_export_rectangle_wkb'
                prior=_safe_wkb(st.session_state.get(stored_key))
                fmap=build_rectangle_selector_map(prior)
                feedback=st_folium(fmap, height=350,width=None,returned_objects=['all_drawings'],
                    key=f'{prefix}_export_rectangle_map')
                drawings=(feedback or {}).get('all_drawings') or []
                if drawings:
                    new=geometry_from_geojson(drawings[-1]);new=valid_polygon(new)
                    if prior is None or new.wkb!=prior.wkb:
                        st.session_state[stored_key]=new.wkb.hex()
                        prior=new
                if prior is None:
                    st.info('Desenhe um retângulo com a ferramenta do mapa para definir a área.');return None
                if st.button('Limpar retângulo',key=f'{prefix}_exp_rect_clear'):
                    st.session_state.pop(stored_key,None)
                    st.rerun()
                return ExportArea('Retângulo desenhado no mapa',prior,'retangulo')

            if kind == 'Ponto com círculo':
                radius=st.slider('Raio da análise (km)',10,200,40,5,key=f'{prefix}_exp_circle_radius')
                mode=st.radio('Selecionar centro',['Clicar no mapa','Digitar coordenadas'],
                              horizontal=True,key=f'{prefix}_exp_circle_method')
                if mode == 'Clicar no mapa':
                    import folium
                    m=folium.Map(location=[-15,-60],zoom_start=3,tiles='CartoDB positron',control_scale=True)
                    prior=st.session_state.get(f'{prefix}_exp_circle_clicked')
                    if prior:
                        folium.Marker(prior,tooltip='Centro selecionado').add_to(m)
                    rv=st_folium(m,height=350,width=None,returned_objects=['last_clicked'],key=f'{prefix}_exp_circle_map')
                    clicked=(rv or {}).get('last_clicked')
                    if isinstance(clicked,dict) and 'lat' in clicked and 'lng' in clicked:
                        new=(round(float(clicked['lat']),6),round(float(clicked['lng']),6))
                        if new != prior:
                            st.session_state[f'{prefix}_exp_circle_clicked']=new
                        prior=new
                    if not prior:
                        st.info('Clique no mapa para marcar o centro do círculo.');return None
                    lat,lon=prior
                    st.caption(f'Centro selecionado: {lat:.5f}°, {lon:.5f}°')
                else:
                    c1,c2=st.columns(2)
                    with c1:lat=st.number_input('Latitude',-84.9,84.9,-15.0,.0001,format='%.5f',key=f'{prefix}_exp_lat')
                    with c2:lon=st.number_input('Longitude',-180.,180.,-60.0,.0001,format='%.5f',key=f'{prefix}_exp_lon')
                if not (-84.9 < lat < 84.9 and -180 <= lon <= 180):
                    raise ValueError('Centro fora do domínio cartográfico.')
                geom=valid_polygon(circular_buffer_geometry(lat,lon,radius))
                return ExportArea(f'Círculo {radius} km — {lat:.4f}°, {lon:.4f}°',geom,'circulo')

            if kind == 'Polígono importado (SHP/KMZ)':
                geom=_safe_wkb(st.session_state.get('fv_user_polygon_wkb'))
                if geom is None:
                    st.warning('Importe uma geometria na aba Tempo Real primeiro.');return None
                return ExportArea('Área importada pelo usuário',geom,'importado')

        except (ValueError,KeyError,FileNotFoundError) as exc:
            st.warning(f'Área de exportação indisponível: {exc}')
        except Exception as exc:
            st.warning('Não foi possível carregar essa geometria. Confira os dados administrativos locais.')
            with st.expander('Detalhes técnicos'):
                st.exception(exc)
        return None
