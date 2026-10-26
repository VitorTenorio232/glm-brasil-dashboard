"""Flash View — pranchas cartográficas científicas para PNG/JPEG.

Módulo independente das rotinas de leitura/agregação GLM. Entradas são resultados
já processados pelo dashboard; nenhuma consulta NOAA/HF ocorre aqui. Tiles de
fundo são obtidos *somente na preparação explícita da exportação*.

CRS do mapa EPSG:3857, dados científicos originalmente em EPSG:4326.
Licenças/atribuições por provedor são mantidas no rodapé da prancha.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional
import math
import re
import unicodedata

import numpy as np
import pandas as pd
from PIL import Image
from pyproj import Transformer
from shapely.ops import transform as shapely_transform
from shapely.geometry import shape as geojson_shape

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.patches import FancyBboxPatch, Rectangle

WGS_TO_WEB = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
WORLD_SIZE = 40075016.68557849

BASEMAPS = {
    'osm': {
        'title': 'Mapa — OpenStreetMap',
        'url': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        'credit': 'Mapa-base: © OpenStreetMap contributors',
    },
    'satellite': {
        'title': 'Satélite — Esri World Imagery',
        'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'credit': 'Mapa-base: Esri, Maxar, Earthstar Geographics e colaboradores GIS',
    },
    'light': {
        'title': 'Claro — CARTO Positron',
        'url': 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
        'credit': 'Mapa-base: © OpenStreetMap contributors, © CARTO',
    },
    'dark': {
        'title': 'Escuro — CARTO Dark Matter',
        'url': 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'credit': 'Mapa-base: © OpenStreetMap contributors, © CARTO',
    },
}

GLM_BANDS = [
    (0.0, 5.0, '#ff3028', '0–5 min'),
    (5.0, 10.0, '#f5bd44', '5–10 min'),
    (10.0, 20.0, '#28c874', '10–20 min'),
    (20.0, 30.0, '#268fff', '20–30 min'),
]

class BasemapUnavailable(RuntimeError):
    """Sem acesso/autorização a tiles cartográficos: não substitua silenciosamente."""

@dataclass(frozen=True)
class BoardMeta:
    product: str
    region: str
    period: str
    source: str = 'NOAA / GOES-R / GLM-L2-LCFA'
    collection: str = 'Geostationary Lightning Mapper — Level 2'
    reference_utc: Optional[datetime] = None
    local_tz: str = 'America/Sao_Paulo'
    resolution: str = 'Não informado'
    institution: str = 'FLASH VIEW • MONITORAMENTO DE RELÂMPAGOS'
    logo_path: Optional[str] = None
    basemap: str = 'satellite'


def safe_name(*parts, extension='png') -> str:
    def clean(item):
        st = unicodedata.normalize('NFKD', str(item))
        st = st.encode('ascii', errors='ignore').decode('ascii')
        st = re.sub(r'[^a-zA-Z0-9_-]+', '_', st).strip('_').lower()
        return st[:50] or 'sem_identificacao'
    return 'flash_view_' + '_'.join(clean(i) for i in parts) + f'.{extension}'


def jpeg_from_png(png: bytes, quality: int = 93) -> bytes:
    with Image.open(BytesIO(png)) as img:
        out = BytesIO()
        img.convert('RGB').save(out, format='JPEG', quality=quality,
                                subsampling=0, optimize=True)
        return out.getvalue()


def _extent_from_bounds(bounds, *, aspect=1.75, margin=0.075):
    """Projeção Web Mercator com padding e proporção exata da janela do mapa.

    bounds: (lon_min, lat_min, lon_max, lat_max), WGS84.
    Output: (xmin, xmax, ymin, ymax) em metros.
    """
    w, s, e, n = map(float, bounds)
    if not (-180 <= w < e <= 180 and -85 <= s < n <= 85):
        raise ValueError(f'Limites geográficos inválidos para Web Mercator: {bounds}')
    x0, y0 = WGS_TO_WEB.transform(w, s)
    x1, y1 = WGS_TO_WEB.transform(e, n)
    cx, cy = (x0 + x1)/2, (y0 + y1)/2
    dx, dy = max(x1-x0, 2000.0), max(y1-y0, 2000.0)
    dx, dy = dx*(1+2*margin), dy*(1+2*margin)
    dx = max(dx, aspect*dy)
    dy = max(dy, dx/aspect)
    return cx-dx/2, cx+dx/2, cy-dy/2, cy+dy/2


def extent_for_geometry(geometry=None, *, lon=None, lat=None, default=(-82,-56,-30,14),
                        aspect=1.75):
    if geometry is not None and not geometry.is_empty:
        b = geometry.bounds
    elif lon is not None and lat is not None and np.size(lon) and np.size(lat):
        b = (np.nanmin(lon), np.nanmin(lat), np.nanmax(lon), np.nanmax(lat))
        if not np.all(np.isfinite(b)):
            b = default
    else:
        b = default
    # Não distorcer silenciosamente recortes além do domínio Web Mercator.
    return _extent_from_bounds(b, aspect=aspect)


def _zoom_for_extent(extent, *, target_pixels=1450):
    span = max(extent[1]-extent[0], extent[3]-extent[2])
    meters_per_pixel = span / max(target_pixels, 256)
    return max(2, min(11, int(math.floor(math.log2(WORLD_SIZE/(256*meters_per_pixel))))))


def _tile_background(ax, extent, basemap, *, background_loader=None):
    """Desenha mosaico em EPSG:3857, sem aplicar a máscara do raster científico.

    background_loader opcional é injeção de dependência para testes OFFLINE.
    Deve retornar (RGB/RGBA array, (xmin,xmax,ymin,ymax)) em EPSG:3857.
    """
    if basemap not in BASEMAPS:
        raise ValueError(f'Fundo desconhecido: {basemap}')
    supplied_loader = background_loader is not None and not getattr(background_loader, "is_real_basemap", False)
    if background_loader is None:
        try:
            import contextily as ctx
        except ImportError as e:
            raise BasemapUnavailable('Instale contextily para exportar o mesmo fundo do mapa: pip install contextily') from e
        def background_loader(ex, source):
            try:
                img, bounds = ctx.bounds2img(ex[0], ex[2], ex[1], ex[3],
                    zoom=_zoom_for_extent(ex), source=source, ll=False, wait=0, max_retries=1)
            except Exception as err:
                raise BasemapUnavailable(
                    f'Não foi possível obter os tiles do fundo {basemap!r}. '
                    'Verifique rede, cota de acesso, licença e disponibilidade do provedor. '
                    'A exportação não substitui o fundo silenciosamente.'
                ) from err
            # contextily: bounds = (w,e,s,n)
            return img, bounds
    image, image_extent = background_loader(extent, BASEMAPS[basemap]['url'])
    if np.ndim(image) != 3 or image.shape[2] not in (3, 4):
        raise BasemapUnavailable('O provedor não retornou um mosaico RGB/RGBA válido.')
    ax.imshow(image, extent=image_extent, origin='upper', zorder=0,
              interpolation='bilinear')
    return ('Fundo demonstrativo/simulado (teste offline; não é o mosaico do dashboard)'
            if supplied_loader else BASEMAPS[basemap]['credit'])


def _project_geom(geom):
    return shapely_transform(WGS_TO_WEB.transform, geom) if geom is not None else None


def _draw_uploaded_shapes(ax, overlay_geojson):
    """Overlay GeoJSON importado pelo usuário, em coordenadas Web Mercator.

    Desenha apenas geometrias recebidas na sessão; NÃO usa a geometria como
    máscara do fundo ou altera as estatísticas científicas.
    """
    if not overlay_geojson:
        return 0
    if not isinstance(overlay_geojson, dict):
        raise ValueError('Camada geográfica importada inválida.')
    features = (overlay_geojson.get('features', [])
                if overlay_geojson.get('type') == 'FeatureCollection'
                else [overlay_geojson])
    if len(features) > 30000:
        raise ValueError('A camada importada excede o limite de 30.000 feições.')
    drawn = 0
    for feature in features:
        try:
            raw = feature.get('geometry') if feature.get('type') == 'Feature' else feature
            if not raw:
                continue
            geom = geojson_shape(raw)
            if geom.is_empty:
                continue
            web_geom = _project_geom(geom)
        except Exception as exc:
            raise ValueError('Geometria inválida em SHP/KMZ/KML/GeoJSON.') from exc
        parts = list(web_geom.geoms) if hasattr(web_geom, 'geoms') else [web_geom]
        for part in parts:
            if part.geom_type == 'Polygon':
                for ring in [part.exterior, *part.interiors]:
                    x, y = ring.xy
                    ax.plot(x, y, color='#092032', lw=3.0, alpha=.9, zorder=16)
                    ax.plot(x, y, color='#00e3ff', lw=1.6, alpha=.99, zorder=17)
                drawn += 1
            elif part.geom_type in ('LineString', 'LinearRing'):
                x, y = part.xy
                ax.plot(x, y, color='#092032', lw=3.0, zorder=16)
                ax.plot(x, y, color='#00e3ff', lw=1.6, zorder=17)
                drawn += 1
            elif part.geom_type == 'Point':
                ax.plot([part.x], [part.y], marker='x', ls='none', color='#00e3ff',
                        ms=8, mew=2.0, zorder=17)
                drawn += 1
    return drawn


def _draw_outline(ax, geom):
    if geom is None or geom.is_empty:
        return
    geom = _project_geom(geom)
    geoms = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    for p in geoms:
        if p.geom_type == 'Polygon':
            outer = [p.exterior] + list(p.interiors)
            for ring in outer:
                xs, ys = ring.xy
                ax.plot(xs, ys, color='black', lw=2.2, alpha=.90, zorder=9)
                ax.plot(xs, ys, color='#f2da54', lw=1.0, alpha=.98, zorder=10)
        elif p.geom_type in ('LineString', 'LinearRing'):
            xs,ys = p.xy
            ax.plot(xs,ys,color='#f2da54',lw=1.35,zorder=9)


def _stats_raster(arr, variable):
    vals = np.asarray(arr, dtype=float)
    finite = vals[np.isfinite(vals)]
    if not finite.size:
        return [('Cobertura válida', 'Sem dados válidos'),
                ('Mínimo', '—'), ('Máximo', '—'), ('Média', '—')]
    minv, maxv, avg = float(finite.min()), float(finite.max()), float(finite.mean())
    if variable == 'flash_count':
        total = float(finite.sum())
        return [('Células válidas', f'{len(finite):,}'.replace(',', '.')),
                ('Mínimo / célula', f'{minv:.3g}'), ('Máximo / célula', f'{maxv:.3g}'),
                ('Σ valores da grade', f'{total:,.3g}'.replace(',', '.'))]
    return [('Pixels válidos', f'{len(finite):,}'.replace(',', '.')),
            ('Mínimo', f'{minv:.3g}'), ('Máximo', f'{maxv:.3g}'),
            ('Média dos pixels', f'{avg:.3g}')]


def _utc_local(reference_utc, timezone_name):
    if reference_utc is None:
        return ''
    t = pd.Timestamp(reference_utc)
    t = t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')
    br = t.tz_convert(timezone_name)
    return f'UTC {t:%d/%m/%Y %H:%M}   |   Brasília {br:%d/%m/%Y %H:%M}'


def _trim(value: str, n=67):
    s = str(value).replace('\n', ' ').strip()
    return s if len(s)<=n else s[:n-1]+'…'


def _draw_header(fig, meta: BoardMeta):
    fig.text(.055,.968, 'FLASH VIEW',fontsize=16,color='#007b93',weight='bold',va='top')
    fig.text(.055,.936,_trim(meta.product, 72),fontsize=22,color='#11273a',
             weight='bold',va='top')
    fig.text(.055,.903,_trim(f'{meta.region}  •  {meta.period}', 102),fontsize=11.5,
             color='#526576',va='top')
    if meta.reference_utc is not None:
        fig.text(.055,.878,_utc_local(meta.reference_utc, meta.local_tz),fontsize=10,
                 color='#526576',va='top')
    # Identidade visual integrada (não presume possuir o logotipo oficial).
    if meta.logo_path and Path(meta.logo_path).is_file():
        try:
            logo = Image.open(meta.logo_path).convert('RGBA')
            ax = fig.add_axes([.84,.911,.105,.069])
            ax.imshow(logo); ax.axis('off')
        except Exception:
            pass
    else:
        fig.text(.945,.947,'⚡',fontsize=22,ha='right',va='top',color='#007b93')
        fig.text(.945,.919,'GLM • NOAA',fontsize=9,ha='right',va='top',color='#576877')
    fig.add_artist(plt.Line2D([.055,.945],[.861,.861],transform=fig.transFigure,
                              color='#dee8ed',lw=1.2))


def _add_cards(fig, meta, metrics, x0=.055, y=.143, w=.89):
    items = [
        ('PRODUTO / FONTE', f'{meta.product} • {meta.source}'),
        ('ÁREA DE INTERESSE', meta.region),
        ('PERÍODO', meta.period),
        ('ESTATÍSTICAS', '  |  '.join(f'{k}: {v}' for k,v in metrics)),
        ('RESOLUÇÃO', meta.resolution),
    ]
    # Três cartões superiores, dois inferiores; dimensões estáveis.
    slots=[(.055,.178,.288),(.354,.178,.288),(.653,.178,.292),(.055,.114,.588),(.653,.114,.292)]
    for (title,content),(left,bottom,width) in zip(items,slots):
        box=FancyBboxPatch((left,bottom),width,.057,boxstyle='round,pad=0.004,rounding_size=0.008',
             transform=fig.transFigure,facecolor='#f3f7fa',edgecolor='#dae4ea',lw=.7)
        fig.add_artist(box)
        fig.text(left+.012,bottom+.039,title,fontsize=8,weight='bold',color='#547080',va='center')
        fig.text(left+.012,bottom+.019,_trim(content, 125 if title=='ESTATÍSTICAS' else int(width*160)),fontsize=8.2,
                 color='#19364a',va='center')


def _footer(fig, meta, carto_credit):
    fig.add_artist(plt.Line2D([.055,.945],[.078,.078],transform=fig.transFigure,
                              color='#d9e5e9',lw=1.0))
    gen = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    fig.text(.055,.060,_trim(f'FONTE: {meta.source}  •  {meta.collection}',125),
             color='#596c78',fontsize=8,va='center')
    fig.text(.055,.043,_trim(carto_credit,135),color='#596c78',fontsize=8,va='center')
    fig.text(.055,.026,f'{meta.institution}  •  Gerado em {gen}',
             color='#71808b',fontsize=7.8,va='center')


def _new_figure(width):
    width = int(width)
    if not 1600 <= width <= 2400:
        raise ValueError('A largura deve estar entre 1600 e 2400 pixels.')
    dpi=160
    fig=plt.figure(figsize=(width/dpi, width/dpi*0.76),dpi=dpi,
                   facecolor='#fff',constrained_layout=False)
    # Área principal: 89% da largura e 59% da altura da prancha.
    ax=fig.add_axes([.055,.302,.89,.541]);ax.set_facecolor('#e9eef2')
    return fig,ax


def _finish(fig, ax, meta, metrics, carto_credit, width, *, legend=None, categorical=False, legend_unit=''):
    ax.tick_params(axis='both',which='both',bottom=False,left=False,
                   labelbottom=False,labelleft=False)
    for s in ax.spines.values():s.set_visible(False)
    _draw_header(fig,meta)
    _add_cards(fig,meta,metrics)
    _footer(fig,meta,carto_credit)
    if legend is not None:
        axlegend=fig.add_axes([.235,.262,.53,.012])
        cb=fig.colorbar(legend,cax=axlegend,orientation='horizontal')
        cb.set_ticks(np.linspace(legend.norm.vmin,legend.norm.vmax,5))
        cb.set_ticklabels([f'{v:.3g}' for v in np.linspace(legend.norm.vmin,legend.norm.vmax,5)])
        cb.ax.tick_params(labelsize=8,pad=4)
        cb.set_label(legend_unit or 'Valor',fontsize=8,labelpad=3)
        cb.ax.xaxis.set_ticks_position('bottom')
        axlegend.set_title('ESCALA DE CORES • VALORES FIXOS POR PRODUTO',
                           fontsize=8,color='#455d69',pad=4)
    elif categorical:
        fig.text(.50,.290,'INTERVALOS DOS FLASHES (MINUTOS)',ha='center',
                 fontsize=8,color='#455d69')
        # Quatro chips igualmente espaçados, centralizados.
        for i,(lo,hi,color,label) in enumerate(GLM_BANDS):
            x=.313 + i*.115
            patch=Rectangle((x,.259),.018,.012,transform=fig.transFigure,
                            facecolor=color,edgecolor='none')
            fig.add_artist(patch)
            fig.text(x+.024,.265,label,fontsize=8,ha='left',va='center',color='#334d5f')
    out=BytesIO();fig.savefig(out,format='png',dpi=160,facecolor='#fff')
    plt.close(fig)
    return out.getvalue()


def render_raster_board(lat,lon,field,*,meta: BoardMeta,variable:str,
                        fixed_range:tuple[float,float],geometry=None,width=1920,
                        unit='',background_loader=None, overlay_geojson=None,
                        cmap_name='turbo'):
    """Prancha raster; dados já processados e mascarados no dashboard.

    Os zeros permanecem zeros; ausência de pixels válidos é explicitada.
    O fundo não recebe a máscara da geometria, apenas o campo temático.
    """
    lat=np.asarray(lat,dtype=float);lon=np.asarray(lon,dtype=float)
    field=np.ma.filled(np.ma.asarray(field,dtype=float),np.nan)
    if lat.ndim!=1 or lon.ndim!=1 or field.shape!=(len(lat),len(lon)):
        raise ValueError('Esperados latitude e longitude 1D e campo [lat,lon].')
    a,b=map(float,fixed_range)
    if not (np.isfinite(a) and np.isfinite(b) and a<b):
        raise ValueError('Escala fixa inválida.')
    fig,ax=_new_figure(width)
    extent=extent_for_geometry(geometry,lon=lon,lat=lat)
    credit=_tile_background(ax,extent,meta.basemap,background_loader=background_loader)
    xx,yy=np.meshgrid(lon,lat)
    mx,my=WGS_TO_WEB.transform(xx,yy)
    # Matriz NaN é transparente; não recorta o mapa-base.
    cmap=plt.colormaps[cmap_name].copy();cmap.set_bad((1,1,1,0))
    if geometry is not None:
        from shapely import contains_xy
        field = np.where(contains_xy(geometry,xx,yy),field,np.nan)
    fieldmasked=np.ma.masked_invalid(field)
    ax.pcolormesh(mx,my,fieldmasked,cmap=cmap,norm=Normalize(vmin=a,vmax=b),
                  shading='nearest',alpha=.86,zorder=2,rasterized=True)
    _draw_outline(ax,geometry)
    _draw_uploaded_shapes(ax,overlay_geojson)
    ax.set_xlim(extent[:2]);ax.set_ylim(extent[2:])
    if not np.isfinite(field).any():
        ax.text(.5,.48,'SEM DADOS VÁLIDOS',transform=ax.transAxes,ha='center',
                va='center',fontsize=15,weight='bold',color='#a1323a',zorder=12,
                bbox=dict(facecolor='white',edgecolor='#dfb8bb',boxstyle='round,pad=.6'))
    metrics=_stats_raster(field,variable)
    sm=ScalarMappable(norm=Normalize(vmin=a,vmax=b),cmap=cmap)
    board=_finish(fig,ax,meta,metrics,credit,width,legend=sm,legend_unit=unit)
    return board


def render_flash_board(flashes:pd.DataFrame,*,meta:BoardMeta,geometry=None,
                       width=1920,observation_end=None,background_loader=None,
                       overlay_geojson=None, extent_override=None):
    """Prancha de flashes observados, sem amostragem para estatística.

    Exibição pode amostrar 25 mil pontos, contagem sempre considera todos.
    """
    data=flashes if flashes is not None else pd.DataFrame()
    fig,ax=_new_figure(width)
    extent=extent_override if extent_override is not None else extent_for_geometry(geometry)
    credit=_tile_background(ax,extent,meta.basemap,background_loader=background_loader)
    plotted=0
    if not data.empty:
        if not {'lat','lon','time_start'}.issubset(data.columns):
            raise ValueError('Dados GLM sem colunas lat/lon/time_start.')
        time=pd.to_datetime(data['time_start'],utc=True,errors='coerce')
        end=pd.Timestamp(observation_end or meta.reference_utc)
        if end.tzinfo is None: end=end.tz_localize('UTC')
        ages=(end-time).dt.total_seconds()/60
        lats=pd.to_numeric(data['lat'],errors='coerce').to_numpy()
        lons=pd.to_numeric(data['lon'],errors='coerce').to_numpy()
        finite=np.isfinite(lats)&np.isfinite(lons)&np.isfinite(ages.to_numpy())
        keep=finite&(ages.to_numpy()>=0)&(ages.to_numpy()<30)
        # Entrada esperada já filtrada pela geometria; valida novamente em caso
        # de uso isolado para evitar estatísticas de fora do polígono.
        if geometry is not None:
            from shapely import contains_xy
            keep &= contains_xy(geometry,lons,lats)
        idx=np.flatnonzero(keep)
        n_total=len(idx)
        if len(idx)>25000:
            rng=np.random.default_rng(173)
            idx=np.sort(rng.choice(idx,25000,replace=False))
        lons=lons[idx];lats=lats[idx];agearr=ages.to_numpy()[idx]
        xm,ym=WGS_TO_WEB.transform(lons,lats)
        for lo,hi,color,label in GLM_BANDS:
            m=(agearr>=lo)&(agearr<hi)
            if m.any():
                ax.scatter(xm[m],ym[m],marker='$⚡$',s=23,c=color,
                           edgecolors='none',alpha=.94,zorder=4,rasterized=True)
                plotted+=int(m.sum())
    else:
        n_total=0
    _draw_outline(ax,geometry)
    n_shapes=_draw_uploaded_shapes(ax,overlay_geojson)
    ax.set_xlim(extent[:2]);ax.set_ylim(extent[2:])
    # A coleta existe, mas zero flashes na janela observada.
    metrics=[('Flashes (0–30 min)',f'{n_total:,}'.replace(',','.')),
             ('Pontos desenhados',f'{plotted:,}'.replace(',','.')),
             ('Janela', '30 minutos'),('Camadas importadas',f'{n_shapes} feições' if n_shapes else 'Nenhuma')]
    return _finish(fig,ax,meta,metrics,credit,width,categorical=True)



def render_glm_board_gif(flashes: pd.DataFrame, end_utc: datetime, *,
                         meta: BoardMeta, geometry=None, overlay_geojson=None,
                         interval_minutes=5, duration_ms=700,
                         width=1600, output_width=1120,
                         background_loader=None) -> bytes:
    """GIF cartográfico com janela móvel de 30 min, fundo e shapes FIXOS.

    Quadros: referência −60, −55, ..., 0 min; cada quadro inclui TODAS as
    quatro faixas [0–5, 5–10, 10–20, 20–30] relativas à referência.
    A consulta de fundo é feita UMA ÚNICA VEZ, antes dos quadros.
    Se falhar, BasemapUnavailable sobe para a interface (não cria GIF vazio).
    """
    if not isinstance(meta, BoardMeta):
        raise TypeError('Informe BoardMeta com fundo, área e período aplicados.')
    if not 5 <= int(interval_minutes) <= 30 or 60 % int(interval_minutes):
        raise ValueError('Intervalo deve dividir 60 minutos (5, 10, 15 ou 30).')
    end = pd.Timestamp(end_utc)
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    # Exigir que o snapshot tenha a janela necessária: não confundir
    # ausência de leitura GLM com ausência observada de flashes.
    times = (pd.to_datetime(flashes['time_start'], utc=True, errors='coerce')
             if flashes is not None and 'time_start' in flashes else pd.Series(dtype='datetime64[ns, UTC]'))
    if times.empty or not times.notna().any():
        raise ValueError('Sem registros GLM no snapshot; não é possível gerar uma animação confiável.')
    # O caller é responsável por solicitar no mínimo 90 minutos da fonte,
    # inclusive se não houver flashes nos primeiros minutos.
    extent=extent_for_geometry(geometry)
    if background_loader is None:
        try:
            import contextily as ctx
        except ImportError as exc:
            raise BasemapUnavailable('Instale contextily para incluir o fundo no GIF.') from exc
        try:
            mosaic, bounds=ctx.bounds2img(extent[0], extent[2], extent[1], extent[3],
                zoom=_zoom_for_extent(extent,target_pixels=1000),
                source=BASEMAPS[meta.basemap]['url'], ll=False, max_retries=1)
        except Exception as exc:
            raise BasemapUnavailable('Não foi possível obter o mapa-base para o GIF. '
                'Confira sua rede e o provedor de tiles; não será gerado GIF sem mapa.') from exc
    else:
        mosaic, bounds=background_loader(extent, BASEMAPS[meta.basemap]['url'])
    def one_background(_extent,_url):
        return mosaic,bounds
    one_background.is_real_basemap = (background_loader is None)
    frames=[]
    for mins_ago in range(60,-1,-int(interval_minutes)):
        ref=end-pd.Timedelta(minutes=mins_ago)
        start=ref-pd.Timedelta(minutes=30)
        if flashes is not None and not flashes.empty:
            selected=flashes.loc[(times >= start) & (times < ref)].copy()
        else:
            selected=pd.DataFrame(columns=['lat','lon','time_start'])
        frame_meta=BoardMeta(
            product=meta.product,region=meta.region,
            period=f'Janela: {start:%d/%m/%Y %H:%M}–{ref:%H:%M} UTC  •  30 min',
            source=meta.source,collection=meta.collection,reference_utc=ref.to_pydatetime(),
            local_tz=meta.local_tz,resolution=meta.resolution,
            institution=meta.institution,logo_path=meta.logo_path,basemap=meta.basemap)
        png=render_flash_board(selected,meta=frame_meta,geometry=geometry,
            width=width,observation_end=ref,background_loader=one_background,
            overlay_geojson=overlay_geojson,extent_override=extent)
        with Image.open(BytesIO(png)) as img:
            rgb=img.convert('RGB')
            if output_width and rgb.width != output_width:
                ht=round(rgb.height*output_width/rgb.width)
                rgb=rgb.resize((int(output_width),ht),Image.Resampling.LANCZOS)
            frames.append(rgb)
    # Paleta fixa: fundo satélite e formas não mudam de cor entre quadros.
    palette=frames[-1].quantize(colors=256,method=Image.Quantize.MEDIANCUT,
                                dither=Image.Dither.NONE)
    quantized=[f.quantize(palette=palette,dither=Image.Dither.NONE) for f in frames]
    out=BytesIO()
    quantized[0].save(out,format='GIF',save_all=True,append_images=quantized[1:],
                      duration=int(duration_ms),loop=0,optimize=False,disposal=2)
    return out.getvalue()

def render_image_board(png_or_jpeg:bytes,*,meta:BoardMeta,width=1920,
                       metric_text='Produto calculado',chart_kind='Gráfico'):
    """Prancha institucional para séries e rankings; NÃO finge ser mapa."""
    fig,ax=_new_figure(width)
    with Image.open(BytesIO(png_or_jpeg)) as img:
        ax.imshow(img.convert('RGB'),interpolation='bilinear',aspect='auto',zorder=1)
    ax.set_xticks([]);ax.set_yticks([])
    return _finish(fig,ax,meta,[('Tipo',chart_kind),('Resultados',metric_text)],
                   'Representação gráfica produzida com os dados GLM, sem mapa-base externo.',width)
