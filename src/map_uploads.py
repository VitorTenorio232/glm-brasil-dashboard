"""Leitura segura de camadas geográficas fornecidas pelo usuário.

Não faz chamadas externas nem grava uploads persistentemente: SHP em ZIP,
KMZ/KML e GeoJSON. Camadas são apenas locais à sessão Streamlit.
"""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

from shapely.geometry import shape, mapping, Polygon, LineString, Point, GeometryCollection
from shapely.ops import unary_union
from shapely.validation import explain_validity

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 85 * 1024 * 1024
MAX_FEATURES = 15000
MAX_DISPLAY_COORDS = 100000


def _zip_members(content: bytes):
    try:
        with ZipFile(BytesIO(content)) as z:
            files = [m for m in z.infolist() if not m.is_dir()]
            if not files:
                raise ValueError('Arquivo ZIP/KMZ vazio.')
            total = sum(m.file_size for m in files)
            if total > MAX_UNPACKED_BYTES:
                raise ValueError('ZIP/KMZ excede 85 MB descompactados.')
            for m in files:
                p = Path(m.filename)
                if p.is_absolute() or '..' in p.parts or m.filename.startswith('/'):
                    raise ValueError('Caminho inseguro dentro do ZIP/KMZ.')
                if (m.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ZIP/KMZ com link simbólico não permitido.')
            return {m.filename: z.read(m) for m in files}
    except BadZipFile as exc:
        raise ValueError('ZIP/KMZ inválido.') from exc


def _kml_coords(text):
    result = []
    for entry in (text or '').replace('\n', ' ').split():
        pieces = entry.split(',')
        if len(pieces) >= 2:
            result.append((float(pieces[0]), float(pieces[1])))
    return result


def _kml_to_geojson(data: bytes):
    # ElementTree não resolve entidades externas; nunca baixar recursos remotos KML.
    root = ET.fromstring(data)
    ns = {'k': 'http://www.opengis.net/kml/2.2'}
    features = []
    for placemark in root.findall('.//k:Placemark', ns):
        name = placemark.findtext('k:name', default='Área importada', namespaces=ns)
        for polygon in placemark.findall('.//k:Polygon', ns):
            outer = polygon.find('k:outerBoundaryIs/k:LinearRing/k:coordinates', ns)
            if outer is None:
                continue
            shell = _kml_coords(outer.text)
            holes = []
            for inner in polygon.findall('k:innerBoundaryIs/k:LinearRing/k:coordinates', ns):
                coords = _kml_coords(inner.text)
                if len(coords) >= 4:
                    holes.append(coords)
            if len(shell) >= 4:
                features.append({'type':'Feature', 'properties':{'name': name},
                                 'geometry': mapping(Polygon(shell, holes))})
        for linestring in placemark.findall('.//k:LineString', ns):
            node = linestring.find('k:coordinates', ns)
            coords = _kml_coords(node.text if node is not None else '')
            if len(coords) >= 2:
                features.append({'type':'Feature', 'properties':{'name':name},
                                 'geometry':mapping(LineString(coords))})
        for point in placemark.findall('.//k:Point', ns):
            node = point.find('k:coordinates', ns)
            coords = _kml_coords(node.text if node is not None else '')
            if coords:
                features.append({'type':'Feature', 'properties':{'name':name},
                                 'geometry':mapping(Point(coords[0]))})
    return {'type':'FeatureCollection', 'features':features}


def _from_shapefile(members: dict):
    shp_names = [name for name in members if name.lower().endswith('.shp')]
    if not shp_names:
        raise ValueError('ZIP não contém arquivo .shp.')
    selected = shp_names[0]
    stem = str(Path(selected).with_suffix('')).lower()
    target = {name: data for name, data in members.items()
              if str(Path(name).with_suffix('')).lower() == stem}
    suffixes = {Path(name).suffix.lower() for name in target}
    if not {'.shp', '.shx', '.dbf', '.prj'}.issubset(suffixes):
        raise ValueError('Shapefile requer .shp, .shx, .dbf e .prj (ZIP).')
    import geopandas as gpd
    with tempfile.TemporaryDirectory(prefix='fv_shape_') as tmp:
        for name, data in target.items():
            # Descarta subdiretórios do ZIP, mantendo apenas um conjunto completo.
            Path(tmp, Path(name).name).write_bytes(data)
        local_file = str(Path(tmp, Path(selected).name))
        gdf = gpd.read_file(local_file)
        if gdf.crs is None:
            raise ValueError('Shapefile sem CRS. Inclua o arquivo .prj.')
        gdf = gdf.to_crs('EPSG:4326')
        return {'type':'FeatureCollection', 'features': [
            {'type':'Feature', 'properties':{'name': f'Feição {i+1}'},
             'geometry':mapping(geom)}
            for i, geom in enumerate(gdf.geometry) if geom is not None and not geom.is_empty
        ]}


def load_user_overlay(filename: str, content: bytes):
    """Retorna (GeoJSON de visualização, geometria poligonal de filtro, n_feicoes).

    Rejeita arquivos grandes e coordenadas fora de lon/lat após reprojeção.
    """
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError('Envie um arquivo não vazio de até 20 MB.')
    extension = Path(filename).suffix.lower()
    if extension == '.kmz':
        members = _zip_members(content)
        kml_files = [name for name in members if name.lower().endswith('.kml')]
        if not kml_files:
            raise ValueError('KMZ não contém KML.')
        raw = _kml_to_geojson(members[kml_files[0]])
    elif extension == '.kml':
        raw = _kml_to_geojson(content)
    elif extension == '.zip':
        raw = _from_shapefile(_zip_members(content))
    elif extension in ('.geojson', '.json'):
        raw = json.loads(content.decode('utf-8-sig'))
    else:
        raise ValueError('Formato não aceito. Utilize KMZ, KML, GeoJSON ou SHP compactado em ZIP.')

    if raw.get('type') == 'FeatureCollection':
        feats = raw.get('features') or []
    elif raw.get('type') == 'Feature':
        feats = [raw]
    else:
        feats = [{'type':'Feature', 'properties':{}, 'geometry':raw}]
    if not feats or len(feats) > MAX_FEATURES:
        raise ValueError(f'Área sem geometrias ou com mais de {MAX_FEATURES} feições.')

    out, polygons = [], []
    for f in feats:
        gj = f.get('geometry')
        if not gj:
            continue
        geom = shape(gj)
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            continue
        x1,y1,x2,y2 = geom.bounds
        if not (-180<=x1<=180 and -180<=x2<=180 and -90<=y1<=90 and -90<=y2<=90):
            raise ValueError('Coordenadas fora de latitude/longitude. Confira o CRS do arquivo.')
        # Simplificação moderada para renderização interativa; mantém geometria original para filtro.
        simplified = geom.simplify(0.0005, preserve_topology=True)
        out.append({'type':'Feature', 'properties':{'name':str((f.get('properties') or {}).get('name','Área importada'))[:120]},
                    'geometry':mapping(simplified)})
        if geom.geom_type in ('Polygon', 'MultiPolygon'):
            polygons.append(geom)
    if not out:
        raise ValueError('Arquivo sem feições geográficas utilizáveis.')
    result = {'type':'FeatureCollection', 'features':out}
    # Limita a geometria retornada ao Streamlit, evitando renderização excessiva.
    if len(json.dumps(result, ensure_ascii=False)) > 15 * 1024 * 1024:
        raise ValueError('Geometria muito detalhada. Simplifique o arquivo no QGIS.')
    filter_geom = unary_union(polygons) if polygons else None
    return result, filter_geom, len(out)
