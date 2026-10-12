"""Exportações científicas PNG, JPEG e GIF para o Flash View.

Mapas exportados são reprojeções simplificadas de coordenadas geográficas
(lon/lat) sem mosaicos Esri/OSM; não são screenshots do mapa web.
"""
from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from PIL import Image

PALETTE = [(0,5,'#ff3028'),(5,10,'#f5bd44'),(10,20,'#28c874'),(20,30,'#268fff')]


def to_jpeg(png_bytes: bytes, quality: int=94) -> bytes:
    with Image.open(BytesIO(png_bytes)) as img:
        out=BytesIO()
        img.convert('RGB').save(out, format='JPEG', quality=quality, optimize=True)
        return out.getvalue()


def time_window_frame(flashes: pd.DataFrame, end_utc: datetime, frame_idx: int,
                      *, frame_minutes: int=5, n_frames: int=12,
                      window_minutes: int | None=None) -> tuple[pd.DataFrame,datetime,datetime]:
    """Seleção temporal para os quadros do GLM.

    Os instantes avançam em passos de cinco minutos. Com window_minutes=30,
    cada quadro inclui quatro faixas completas e usa a hora final do quadro
    como referência para calcular as cores dos flashes.
    """
    end = pd.Timestamp(end_utc)
    if end.tzinfo is None: end = end.tz_localize('UTC')
    else: end = end.tz_convert('UTC')
    idx = max(0, min(n_frames-1, int(frame_idx)))
    frame_end = end - pd.Timedelta(minutes=(n_frames-idx-1)*frame_minutes)
    frame_start = frame_end - pd.Timedelta(minutes=window_minutes or frame_minutes)
    if flashes is None or flashes.empty or 'time_start' not in flashes:
        return pd.DataFrame(columns=['lat','lon','time_start']), frame_start.to_pydatetime(), frame_end.to_pydatetime()
    ts = pd.to_datetime(flashes['time_start'], utc=True, errors='coerce')
    selected = flashes.loc[(ts>=frame_start)&(ts<frame_end)].copy()
    return selected,frame_start.to_pydatetime(),frame_end.to_pydatetime()


def _lonlat_extent(df, geometry):
    xmin,ymin,xmax,ymax = -82.,-57.,-30.,15.
    if geometry is not None and not geometry.is_empty:
        a,b,c,d=geometry.bounds
        dx=max(0.7,(c-a)*0.09);dy=max(0.7,(d-b)*0.09)
        return a-dx,c+dx,b-dy,d+dy
    if df is not None and len(df)>2:
        xs=pd.to_numeric(df['lon'],errors='coerce').dropna()
        ys=pd.to_numeric(df['lat'],errors='coerce').dropna()
        if len(xs)>3 and len(ys)>3:
            a,c=np.nanpercentile(xs,[1,99]); b,d=np.nanpercentile(ys,[1,99])
            if c-a<0.1: c=a+1
            if d-b<0.1: d=b+1
            pad_x=max(1,(c-a)*0.1);pad_y=max(1,(d-b)*0.1)
            return a-pad_x,c+pad_x,b-pad_y,d+pad_y
    return xmin,xmax,ymin,ymax


def _draw_boundary(ax, geom):
    if geom is None or geom.is_empty: return
    kind=geom.geom_type
    if kind in ('Polygon','MultiPolygon'):
        geoms=[geom] if kind=='Polygon' else list(geom.geoms)
        for poly in geoms:
            x,y=poly.exterior.xy
            ax.plot(x,y,color='#facc15',linewidth=1.6,zorder=8)
            for ring in poly.interiors:
                xx,yy=ring.xy; ax.plot(xx,yy,color='#facc15',linewidth=0.9,zorder=8)
    elif kind in ('LineString','LinearRing'):
        x,y=geom.xy;ax.plot(x,y,color='#facc15',linewidth=1.5,zorder=8)
    elif kind in ('MultiLineString','GeometryCollection'):
        for g in geom.geoms:_draw_boundary(ax,g)
    elif kind=='Point': ax.scatter([geom.x],[geom.y],marker='x',c='#facc15',s=60)


def render_flash_png(flashes: pd.DataFrame, *, title='Flash View | GLM',
                     subtitle='', geometry=None, observation_end=None,
                     extent=None, dpi=135, max_points=22000) -> bytes:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data = flashes.copy() if flashes is not None else pd.DataFrame()
    if not data.empty and len(data)>max_points:
        data=data.sample(n=max_points,random_state=37)
    fig,ax=plt.subplots(figsize=(12.8,7.2), dpi=dpi)
    fig.patch.set_facecolor('#080f1e');ax.set_facecolor('#101c2c')
    if extent is None: extent=_lonlat_extent(data,geometry)
    ax.set_xlim(extent[0],extent[1]);ax.set_ylim(extent[2],extent[3])
    ax.grid(True,color='#324459',linewidth=0.65,alpha=.5)
    if not data.empty and {'lat','lon'}.issubset(data.columns):
        lats=pd.to_numeric(data['lat'],errors='coerce');lons=pd.to_numeric(data['lon'],errors='coerce')
        times=pd.to_datetime(data['time_start'],utc=True,errors='coerce') if 'time_start' in data else None
        if observation_end is not None and times is not None:
            ages=(pd.Timestamp(observation_end)-times).dt.total_seconds()/60.
        elif 'age_minutes' in data:
            ages=pd.to_numeric(data['age_minutes'],errors='coerce')
        else:
            ages=pd.Series(0.,index=data.index)
        older=(ages>=30)&(ages<=60)
        if older.any():ax.scatter(lons[older],lats[older],s=5,c='#7b8da8',alpha=.4,linewidths=0,label='30–60 min')
        for lo,hi,color in reversed(PALETTE):
            mask=(ages>=lo)&(ages<hi)&lats.notna()&lons.notna()
            if mask.any():
                ax.scatter(lons[mask],lats[mask],s=8,c=color,alpha=.82,edgecolors='none',label=f'{lo}–{hi} min')
    _draw_boundary(ax,geometry)
    ax.set_xlabel('Longitude',color='#a9bdd3');ax.set_ylabel('Latitude',color='#a9bdd3')
    ax.tick_params(colors='#a9bdd3')
    for side in ax.spines.values():side.set_color('#42556e')
    fig.text(.055,.965,title,color='white',fontsize=17,weight='bold',va='top')
    fig.text(.055,.924,subtitle,color='#b7c5d7',fontsize=10,va='top')
    fig.text(.055,.024,'GLM-L2-LCFA • NOAA  |  Mapa científico de pontos (sem imagem de satélite)',
             color='#9fb3c8',fontsize=8)
    handles,labels=ax.get_legend_handles_labels()
    if handles:
        leg=ax.legend(loc='upper right',facecolor='#15263a',edgecolor='#45576e',labelcolor='white',fontsize=9)
    fig.subplots_adjust(left=.075,right=.975,top=.89,bottom=.10)
    buf=BytesIO();fig.savefig(buf,format='png',dpi=dpi,facecolor=fig.get_facecolor());plt.close(fig)
    return buf.getvalue()


def render_glm_gif(flashes: pd.DataFrame, end_utc: datetime, *,geometry=None,
                   interval_minutes=5, duration_ms=650) -> bytes:
    """12 janelas móveis de 30 min. Sem screenshots/tiles de terceiros."""
    frames=[]
    extent=_lonlat_extent(flashes,geometry)
    for idx in range(12):
        frame,start,end=time_window_frame(flashes,end_utc,idx,window_minutes=30)
        image_bytes=render_flash_png(frame,title='Flash View | Evolução de flashes (1 h)',
            subtitle=f'UTC: {start:%d/%m/%Y %H:%M} – {end:%H:%M} | Quadro {idx+1}/12 | Flashes: {len(frame):,}',
            geometry=geometry,observation_end=end,extent=extent,dpi=90,max_points=12000)
        with Image.open(BytesIO(image_bytes)) as pic:
            frames.append(pic.convert('P',palette=Image.Palette.ADAPTIVE, colors=128))
    out=BytesIO()
    frames[0].save(out,format='GIF',save_all=True,append_images=frames[1:],
                   duration=int(duration_ms),loop=0,optimize=True)
    return out.getvalue()


def render_ranking_png(table: pd.DataFrame, *,title: str, top_n=15)->bytes:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    df=table.head(top_n)
    if df.empty: raise ValueError('Ranking vazio')
    fig,ax=plt.subplots(figsize=(11.5,max(4,0.45*len(df)+1.6)),dpi=145)
    fig.patch.set_facecolor('#0c1423');ax.set_facecolor('#0c1423')
    vals=pd.to_numeric(df['Valor'],errors='coerce').fillna(0).to_numpy()
    labels=df['Local'].astype(str).tolist()
    ax.barh(range(len(vals)),vals,color='#23a7d6')
    ax.set_yticks(range(len(vals)),labels,color='white',fontsize=9)
    ax.invert_yaxis();ax.tick_params(axis='x',colors='#bbcce0')
    for s in ax.spines.values():s.set_visible(False)
    ax.grid(axis='x',alpha=.2,color='white')
    ax.set_axisbelow(True)
    ax.set_title(title,color='white',loc='left',fontsize=16,weight='bold',pad=15)
    fig.subplots_adjust(left=.36,right=.96,top=.90,bottom=.10)
    buf=BytesIO();fig.savefig(buf,format='png',facecolor=fig.get_facecolor());plt.close(fig)
    return buf.getvalue()
