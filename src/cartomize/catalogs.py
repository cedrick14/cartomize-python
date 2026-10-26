"""STAC search, bounded asset downloads and explicit multisensor scene metadata."""
from pathlib import Path
from urllib.parse import urlsplit,urljoin,urlencode
from urllib.request import Request,urlopen
import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from .storage import read_json,save_json,new_directory
from .imagery import _check_cancel


def _url(value):
    parts=urlsplit(str(value))
    if parts.scheme not in {'https','http'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('Indiquer une URL HTTP(S) sans identifiant intégré.')
    return str(value)


def _fetch_json(url,*,body=None,timeout=60):
    request=Request(_url(url),data=json.dumps(body).encode() if body is not None else None,
                    headers={'Accept':'application/geo+json, application/json','Content-Type':'application/json','User-Agent':'Cartomize'})
    with urlopen(request,timeout=timeout) as response:
        content=response.read(50_000_001)
        if len(content)>50_000_000:raise ValueError('Réponse STAC trop volumineuse.')
    return json.loads(content)


def search_stac(endpoint,*,bbox=None,intersects=None,datetime_range=None,collections=(),limit=20,timeout=60,cancel=None):
    """Search a STAC Item Search endpoint, following GET/POST pagination.

    The endpoint and any access to protected collections are supplied by the
    caller. Authentication and provider-specific URL signing must be configured
    before requesting protected assets.
    """
    import numpy as np
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=1000:raise ValueError('La limite doit être comprise entre 1 et 1 000 scènes.')
    if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not np.isfinite(timeout) or timeout<=0:raise ValueError('Le délai de requête doit être positif et fini.')
    if datetime_range is not None and (not isinstance(datetime_range,str) or not datetime_range.strip()):raise ValueError('datetime_range doit être une date ou un intervalle STAC.')
    if collections is not None and (not isinstance(collections,(list,tuple)) or any(not isinstance(v,str) or not v.strip() for v in collections)):raise ValueError('collections doit être une liste d’identifiants STAC.')
    if bbox is not None and intersects is not None:raise ValueError('Choisir bbox ou intersects, pas les deux.')
    params={'limit':min(limit,100)}
    if bbox is not None:
        values=np.asarray(bbox,dtype=float)
        if values.shape!=(4,) or not np.isfinite(values).all() or not (-180<=values[0]<values[2]<=180 and -90<=values[1]<values[3]<=90):raise ValueError('Emprise WGS84 : [ouest, sud, est, nord].')
        params['bbox']=','.join(map(str,bbox))
    geometry_mapping=None
    if intersects is not None:
        from shapely.geometry import shape,mapping
        from shapely import get_coordinates
        try:geometry=shape(intersects)
        except (TypeError,ValueError,AttributeError,KeyError) as exc:raise ValueError('intersects doit être une géométrie GeoJSON WGS84.') from exc
        coordinates=get_coordinates(geometry)
        if geometry.is_empty or not geometry.is_valid or coordinates.shape[0]==0 or not np.isfinite(coordinates).all():raise ValueError('Géométrie de recherche vide ou invalide.')
        if (np.abs(coordinates[:,0])>180).any() or (np.abs(coordinates[:,1])>90).any():raise ValueError('La géométrie intersects doit être en WGS84 (longitude/latitude).')
        geometry_mapping=mapping(geometry)
    if datetime_range:params['datetime']=datetime_range
    if collections:params['collections']=','.join(collections)
    endpoint=_url(str(endpoint).rstrip('/'))
    if urlsplit(endpoint).query:raise ValueError('Fournir la racine STAC ou son URL /search sans paramètres de requête.')
    url=endpoint if urlsplit(endpoint).path.endswith('/search') else endpoint+'/search'
    if geometry_mapping is not None:
        # POST avoids truncating a real study polygon in a URL length limit.
        body={**params,'intersects':geometry_mapping}
        if collections:body['collections']=list(collections)
    else:
        url+='?'+urlencode(params);body=None
    seen=set();items=[];ids=set()
    while url and len(items)<limit:
        _check_cancel(cancel);key=(url,json.dumps(body,sort_keys=True))
        if key in seen:raise ValueError('Boucle de pagination STAC.')
        if len(seen)>=100:raise ValueError('Pagination STAC excessive.')
        seen.add(key);document=_fetch_json(url,body=body,timeout=timeout)
        if not isinstance(document,dict) or document.get('type')!='FeatureCollection' or not isinstance(document.get('features'),list):raise ValueError('La réponse ne contient pas une collection STAC valide.')
        links=document.get('links',[])
        if not isinstance(links,list) or any(not isinstance(link,dict) or not isinstance(link.get('href'),str) for link in links):raise ValueError('Liens de pagination STAC invalides.')
        for item in document['features']:
            _stac_item(item)
            identity=(item.get('collection'),item.get('id'))
            if identity not in ids:
                ids.add(identity);record=copy.deepcopy(item)
                item_base=next((urljoin(url,l['href']) for l in record.get('links',[]) if l.get('rel')=='self'),url)
                for asset in record.get('assets',{}).values():asset['href']=urljoin(item_base,asset['href'])
                items.append(record)
                if len(items)>=limit:break
        link=next((l for l in links if l.get('rel')=='next'),None)
        if link:
            method=str(link.get('method','GET')).upper()
            if method not in {'GET','POST'}:raise ValueError('Méthode de pagination STAC non prise en charge.')
            if link.get('headers'):raise ValueError('La pagination impose des en-têtes d’authentification explicites.')
            url=urljoin(url,link['href'])
            if method=='POST':
                next_body=link.get('body',{})
                if not isinstance(next_body,dict):raise ValueError('Corps de pagination STAC invalide.')
                body={**(body or {}),**next_body} if link.get('merge') else next_body
            else:body=None
        else:url=None
    return dict(type='FeatureCollection',features=items,links=[],numberReturned=len(items),cartomize_limit=limit)


def _stac_profile(item):
    """Recognize declared products, never a wavelength from a filename alone."""
    properties=item.get('properties',{})
    collection=str(item.get('collection','')).lower()
    platform=str(properties.get('platform') or properties.get('constellation') or 'stac')
    normalized=platform.lower().replace(' ','-').replace('_','-')
    level=str(properties.get('processing:level','custom'))
    sentinel=(collection=='sentinel-2-l2a' or properties.get('s2:product_type')=='S2MSI2A')
    if sentinel and re.fullmatch(r'sentinel-?2[a-c]?',normalized):
        return 'sentinel','sentinel-2','L2A-SR'
    landsat=re.fullmatch(r'landsat-?([45789])',normalized)
    correction=properties.get('landsat:correction') or properties.get('landsat:processing_level') or level
    collection_number=str(properties.get('landsat:collection_number','')).lstrip('0')
    if landsat and (collection in {'landsat-c2-l2','landsat-c2l2-sr'} or (collection_number=='2' and correction in {'L2SP','L2SR','C2-L2-SR'})):
        return 'landsat',f'landsat-{landsat.group(1)}','C2-L2-SR'
    return None,platform,level


def _stac_item(item):
    if not isinstance(item,dict) or item.get('type')!='Feature' or not item.get('stac_version') or not isinstance(item.get('id'),str) or not item['id'].strip():
        raise ValueError('Objet STAC Item avec identifiant attendu.')
    if item.get('collection') is not None and (not isinstance(item['collection'],str) or not item['collection'].strip()):raise ValueError('Identifiant de collection STAC invalide.')
    if not isinstance(item.get('assets'),dict) or not item['assets']:
        raise ValueError('Le STAC Item ne contient aucun asset.')
    if not isinstance(item.get('properties',{}),dict):raise ValueError('Propriétés STAC invalides.')
    for key,asset in item['assets'].items():
        if not isinstance(key,str) or not key or not isinstance(asset,dict) or not isinstance(asset.get('href'),str) or not asset['href']:
            raise ValueError('Clé, métadonnées ou URL d’asset STAC invalides.')
        if not isinstance(asset.get('roles',[]),list) or any(not isinstance(v,str) for v in asset.get('roles',[])):
            raise ValueError('Rôles d’asset STAC invalides : '+key)
    links=item.get('links',[])
    if not isinstance(links,list) or any(not isinstance(link,dict) or not isinstance(link.get('href'),str) for link in links):raise ValueError('Liens de STAC Item invalides.')
    for key in ('datetime','start_datetime'):
        if item.get('properties',{}).get(key) is not None and not isinstance(item['properties'][key],str):raise ValueError('Date STAC invalide.')


def _asset_local_path(item,key,base):
    if key not in item['assets']:raise ValueError('Asset absent : '+str(key))
    href=item['assets'][key].get('href')
    if not isinstance(href,str) or not href:raise ValueError('Chemin d’asset absent : '+key)
    if urlsplit(href).scheme.lower() in {'http','https','s3','gs','az'}:
        raise ValueError('Télécharger les assets avant le prétraitement : '+key)
    path=Path(href)
    if not path.is_absolute():path=Path(base or '.')/path
    if not path.is_file():raise FileNotFoundError(path)
    return path


def _native_code(name):
    match=re.fullmatch(r'(?:(?:SR|OLI|TM|ETM)_)?(B\d{1,2}[A-Z]?)',str(name).upper())
    if match:
        code=match.group(1)
        return 'B'+code[1:].zfill(2) if code[1:].isdigit() else code
    return None


def _band_role(family,sensor,key,band,override=None):
    from .scenes import SENTINEL,LANDSAT_OLI,LANDSAT_TM
    code=_native_code(band.get('name')) or _native_code(key)
    if override is not None:return override,code
    common=band.get('eo:common_name') or band.get('common_name')
    if family=='sentinel':
        role=SENTINEL.get(code)
        if role:return role,code
        named={**{v:v for v in SENTINEL.values()},'nir08':'nir_narrow','nir09':'water_vapour','swir16':'swir1','swir22':'swir2'}
        return named.get(key.lower()) or named.get(common),code
    if family=='landsat':
        roles=LANDSAT_OLI if sensor in {'landsat-8','landsat-9'} else LANDSAT_TM
        code='B'+str(int(code[1:])) if code and code[1:].isdigit() else code
        if code in roles:return roles[code],code
        aliases={'swir16':'swir1','swir22':'swir2','nir08':'nir'}
        role=aliases.get(common,common) or aliases.get(key.lower(),key.lower())
        return (role if role in set(roles.values()) else None),code
    aliases={'swir16':'swir1','swir22':'swir2','nir08':'nir','nir09':'nir_narrow'}
    return aliases.get(common,common),code


def _spectral_assets(item,band_mapping=None,*,require_bands=True):
    """Return one scientific asset per role, retaining its native band index."""
    _stac_item(item)
    family,sensor,_=_stac_profile(item);mapping=band_mapping or {}
    if not isinstance(mapping,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in mapping.items()):
        raise ValueError('band_mapping doit associer une clé d’asset à un rôle spectral non vide.')
    missing=set(mapping)-set(item['assets'])
    if missing:raise ValueError('Assets absents de band_mapping : '+', '.join(sorted(missing)))
    candidates={}
    for key,asset in item['assets'].items():
        if not isinstance(asset,dict):raise ValueError('Métadonnées d’asset invalides : '+key)
        roles=set(asset.get('roles',[]))
        if roles & {'visual','thumbnail','overview','tiles'} or key.lower() in {'visual','visual-jp2','thumbnail','rendered_preview','tilejson'}:
            if key in mapping:raise ValueError('Une composition visuelle ne peut pas servir de bande scientifique : '+key)
            continue
        if roles & {'metadata','saturation','cloud','cloud-shadow','water-mask'} and key not in mapping:continue
        metadata=asset.get('bands') or asset.get('eo:bands') or []
        if not metadata and len(item['assets'])==1:
            metadata=item.get('properties',{}).get('bands') or item.get('properties',{}).get('eo:bands') or []
        if not metadata and (family or key in mapping):metadata=[dict(name=key)]
        if key in mapping and len(metadata)!=1:raise ValueError('band_mapping exige un asset à une seule bande : '+key)
        if not isinstance(metadata,list):raise ValueError('Liste de bandes STAC invalide : '+key)
        raster=asset.get('raster:bands') or []
        if not isinstance(raster,list):raise ValueError('Liste raster:bands invalide : '+key)
        for index,band in enumerate(metadata,1):
            if not isinstance(band,dict):raise ValueError('Métadonnées de bande invalides : '+key)
            role,code=_band_role(family,sensor,key,band,mapping.get(key))
            if not role:continue
            numeric={**asset,**(raster[index-1] if index<=len(raster) else {}),**band}
            record=dict(key=key,index=index,role=role,code=code,numeric=numeric)
            candidates.setdefault(role,[]).append(record)
    selected=[]
    for role,records in candidates.items():
        if len(records)>1:
            # Earth Search exposes a COG and a JP2 copy of the same native band.
            # Other duplicate scientific roles require an explicit asset choice.
            keys={r['key'] for r in records}
            canonical=[r for r in records if {r['key'],r['key']+'-jp2'}==keys]
            if family and len(records)==2 and len(canonical)==1 and len({r['code'] for r in records})==1:
                selected.append(canonical[0]);continue
            raise ValueError('Plusieurs bandes décrivent le même rôle spectral : '+role+'. Sélectionner une seule variante.')
        selected.append(records[0])
    if not selected and require_bands:raise ValueError('Déclarer les rôles spectraux dans STAC ou band_mapping.')
    return selected


def _companion_key(item,names):
    candidates=[key for key in item['assets'] if key.lower() in names]
    if len(candidates)>1:raise ValueError('Plusieurs masques ou métadonnées équivalents : '+', '.join(candidates))
    if candidates:return candidates[0]
    return None


def _mask_assets(item,quality_asset=None,quality_kind=None,saturation_asset=None):
    family,_,_=_stac_profile(item)
    expected='landsat_qa' if family=='landsat' else 'sentinel_scl' if family=='sentinel' else None
    automatic=_companion_key(item,{'qa_pixel'}) if family=='landsat' else _companion_key(item,{'scl'}) if family=='sentinel' else None
    if automatic is None and family=='sentinel':automatic=_companion_key(item,{'scl-jp2'})
    quality=quality_asset if quality_asset is not None else automatic
    if quality is not None:
        if quality not in item['assets']:raise ValueError('Asset de qualité absent : '+str(quality))
        kind=quality_kind or (expected if quality==automatic else None)
        if kind not in {'landsat_qa','sentinel_scl','valid_mask'}:raise ValueError('Déclarer quality_kind pour le masque choisi.')
    else:
        if quality_kind is not None:raise ValueError('quality_kind exige un asset de qualité.')
        kind=None
    saturation=saturation_asset
    if saturation is None and family=='landsat':saturation=_companion_key(item,{'qa_radsat'})
    if saturation is not None and saturation not in item['assets']:raise ValueError('Asset de saturation absent : '+str(saturation))
    return quality,kind,saturation


def _product_metadata_key(item):
    key=_companion_key(item,{'product-metadata','product_metadata'})
    if key:return key
    found=[k for k,a in item['assets'].items() if Path(urlsplit(a.get('href','')).path).name.upper()=='MTD_MSIL2A.XML']
    if len(found)>1:raise ValueError('Plusieurs fichiers MTD_MSIL2A.xml dans le STAC Item.')
    return found[0] if found else None


def _declares_calibration(numeric):
    return any(key in numeric for key in ('scale','offset','raster:scale','raster:offset'))


def _earthsearch_harmonized_cog(item,key):
    """The legacy provider flag applies to its harmonized COG, never raw JP2.

    Producer clarification: Element84/earth-search#9, comment 1663252010.
    Legacy STAC offset may still describe the original SAFE DN even when the
    COG has already had BOA_ADD_OFFSET applied. Keep original metadata intact.
    """
    asset=item['assets'][key]
    return (item.get('collection')=='sentinel-2-l2a' and
            item.get('properties',{}).get('earthsearch:boa_offset_applied') is True and
            not key.lower().endswith('-jp2') and
            str(asset.get('type','')).lower().startswith('image/tiff'))


def stac_asset_keys(item,*,band_order=None,band_mapping=None,quality_asset=None,quality_kind=None,
                    saturation_asset=None,include_quality=True,include_saturation=True):
    """Select scientific assets and required companions before downloading.

    Known Landsat C2 L2 and Sentinel-2 L2A profiles map native band codes and
    QA/SCL assets. Other products need declared spectral metadata or mappings.
    Sentinel XML is retained when calibration is not declared on selected bands.
    """
    records=_spectral_assets(item,band_mapping)
    available={r['role'] for r in records}
    names=list(band_order) if band_order is not None else [r['role'] for r in records]
    if isinstance(band_order,str) or not names or any(not isinstance(n,str) or not n for n in names) or len(set(names))!=len(names):raise ValueError('Choisir des rôles spectraux uniques et non vides.')
    missing=set(names)-available
    if missing:raise ValueError('Bandes spectrales absentes : '+', '.join(sorted(missing)))
    records=[r for r in records if r['role'] in names]
    keys=list(dict.fromkeys(r['key'] for r in records))
    quality,_,saturation=_mask_assets(item,quality_asset,quality_kind,saturation_asset)
    if include_quality:
        if quality is None:raise ValueError('Aucun masque QA/SCL déclaré pour cette scène ; fournir quality_asset et quality_kind ou désactiver explicitement le masquage.')
        keys.append(quality)
    if include_saturation and saturation is not None:keys.append(saturation)
    if _stac_profile(item)[0]=='sentinel' and any(not _declares_calibration(r['numeric']) for r in records):
        metadata=_product_metadata_key(item)
        if metadata is not None:keys.append(metadata)
    return tuple(dict.fromkeys(keys))


def _sentinel_xml_calibration(item,base):
    from .scenes import _S2_BANDS
    key=_product_metadata_key(item)
    if key is None:return None
    path=_asset_local_path(item,key,base)
    if path.stat().st_size>20_000_000:raise ValueError('Métadonnées Sentinel trop volumineuses.')
    quantification=None;baseline=None;offsets={}
    try:root=ET.parse(path).getroot()
    except ET.ParseError as exc:raise ValueError('Métadonnées Sentinel XML invalides : '+str(path)) from exc
    for node in root.iter():
        tag=node.tag.rsplit('}',1)[-1]
        if tag=='BOA_QUANTIFICATION_VALUE':quantification=float(node.text)
        elif tag=='PROCESSING_BASELINE':baseline=float(node.text)
        elif tag=='BOA_ADD_OFFSET':
            index=int(node.attrib['band_id'])
            if not 0<=index<len(_S2_BANDS):raise ValueError('Identifiant de bande Sentinel inconnu dans BOA_ADD_OFFSET.')
            offsets[_S2_BANDS[index]]=float(node.text)
    import numpy as np
    if quantification is None or not np.isfinite(quantification) or quantification<=0:raise ValueError('BOA_QUANTIFICATION_VALUE absent ou invalide.')
    if not offsets and (baseline is None or baseline>=4):raise ValueError('BOA_ADD_OFFSET absent pour ce produit Sentinel ; ne pas supposer un décalage nul.')
    return quantification,offsets,baseline


def scene_from_stac(item,*,base=None,band_mapping=None,quality_asset=None,quality_kind=None,saturation_asset=None):
    """Load local STAC scientific bands, calibration and quality companions.

    Product profiles only apply to declared Landsat C2 L2 / Sentinel-2 L2A.
    STAC scale/offset take precedence, except the documented Earth Search
    legacy harmonized-COG flag prevents applying its already applied offset.
    Missing Sentinel calibration is read from product XML (or explicit GDAL
    scale/offset), never guessed from a date.
    """
    from .scenes import Scene,Band
    records=_spectral_assets(item,band_mapping)
    family,sensor,level=_stac_profile(item)
    quality,kind,saturation=_mask_assets(item,quality_asset,quality_kind,saturation_asset)
    quality_path=_asset_local_path(item,quality,base) if quality is not None else None
    saturation_path=_asset_local_path(item,saturation,base) if saturation is not None else None
    bands={};notes=[];xml=None;xml_loaded=False
    for record in records:
        key,index,role=record['key'],record['index'],record['role']
        path=_asset_local_path(item,key,base);numeric=record['numeric']
        scale=numeric.get('raster:scale',numeric.get('scale',1.))
        offset=numeric.get('raster:offset',numeric.get('offset',0.))
        unit=numeric.get('unit','reflectance' if family else 'source units')
        nodata=numeric.get('nodata',0 if family else None)
        if not _declares_calibration(numeric):
            if family=='landsat':
                scale,offset=.0000275,-.2
                notes.append('Calibration native Landsat Collection 2 L2 SR appliquée à '+role+'.')
            elif family=='sentinel':
                if not xml_loaded:xml=_sentinel_xml_calibration(item,base);xml_loaded=True
                if xml is not None:
                    quantification,offsets,baseline=xml
                    code=record['code']
                    if code is None:raise ValueError('Code de bande Sentinel nécessaire pour lire les offsets XML : '+key)
                    if (baseline is None or baseline>=4) and code not in offsets:raise ValueError('BOA_ADD_OFFSET absent pour '+code+'.')
                    scale,offset=1/quantification,offsets.get(code,0)/quantification
                    notes.append('Calibration Sentinel lue dans les métadonnées produit pour '+role+'.')
                else:
                    import rasterio
                    with rasterio.open(path) as source:
                        if index>source.count:raise ValueError('Indice de bande hors du raster : '+key)
                        scale,offset=source.scales[index-1],source.offsets[index-1]
                    if scale==1 and offset==0:raise ValueError('Calibration Sentinel absente : conserver product-metadata / MTD_MSIL2A.xml ou déclarer scale et offset dans le STAC.')
                    notes.append('Calibration Sentinel lue dans le raster pour '+role+'.')
            else:notes.append('Calibration non déclarée pour '+role+' : unités source conservées.')
        if family=='sentinel' and _earthsearch_harmonized_cog(item,key):
            notes.append(f'Earth Search COG harmonisé {key} : scale déclaré={scale}, offset déclaré={offset}, '
                         'offset effectif=0 ; earthsearch:boa_offset_applied=true, aucune seconde application du décalage BOA.')
            offset=0.
        if isinstance(nodata,str):
            try:nodata=float(nodata)
            except ValueError as exc:raise ValueError('Valeur NoData STAC invalide pour '+role+'.') from exc
        bands[role]=Band(path,index=index,scale=scale,offset=offset,nodata=nodata,unit=unit)
    properties=item.get('properties',{})
    return Scene(item['id'],bands,sensor=sensor,
                 acquired=(properties.get('datetime') or properties.get('start_datetime') or '')[:10] or None,
                 level=level,quality=quality_path,quality_kind=kind,saturation=saturation_path,notes=tuple(notes))


def load_scenes_manifest(path,*,band_mapping=None,quality_asset=None,quality_kind=None,saturation_asset=None):
    """Load local STAC Items/collections or cartomize.scenes.v1 manifests."""
    from .scenes import Scene,Band
    path=Path(path).resolve();document=read_json(path)
    options=dict(base=path.parent,band_mapping=band_mapping,quality_asset=quality_asset,
                 quality_kind=quality_kind,saturation_asset=saturation_asset)
    if document.get('stac_version') and document.get('type')=='Feature':return [scene_from_stac(document,**options)]
    if document.get('type')=='FeatureCollection':
        scenes=[scene_from_stac(item,**options) for item in document['features']]
        if not scenes:raise ValueError('Le manifeste ne contient aucune scène.')
        if len({scene.scene_id for scene in scenes})!=len(scenes):raise ValueError('Identifiants de scènes dupliqués dans le manifeste.')
        return scenes
    if document.get('schema')!='cartomize.scenes.v1':raise ValueError('Manifeste de scènes ou STAC attendu.')
    if any(value is not None for value in (band_mapping,quality_asset,quality_kind,saturation_asset)):
        raise ValueError('Les correspondances STAC ne s’appliquent pas à un manifeste cartomize.scenes.v1 déjà explicite.')
    scenes=[]
    for raw in document['scenes']:
        row=dict(raw);assets={}
        for name,value in row.pop('bands').items():
            band=dict(value) if isinstance(value,dict) else dict(path=value);asset=Path(band['path'])
            band['path']=asset if asset.is_absolute() else path.parent/asset
            if not band['path'].is_file():raise FileNotFoundError(band['path'])
            assets[name]=Band(**band)
        for name in ('quality','saturation'):
            if row.get(name):
                asset=Path(row[name]);row[name]=asset if asset.is_absolute() else path.parent/asset
        scenes.append(Scene(bands=assets,**row))
    if not scenes:raise ValueError('Le manifeste ne contient aucune scène.')
    return scenes


def download_stac(source,destination,*,assets=None,include_companions=True,max_bytes=10_000_000_000,timeout=60,progress=None,cancel=None):
    """Download selected HTTP(S) STAC assets atomically; retain local metadata.

    Known optical products default to scientific bands plus QA/SCL, saturation
    and required calibration metadata, excluding previews and alternate JP2s.
    Explicit asset lists retain required companions unless include_companions
    is false. Other products retain their explicit asset semantics.
    Hashes are computed for every completed file and advertised SHA256 checksums
    are verified when present. No partial directory survives a failed transfer.
    """
    import numpy as np
    if not isinstance(max_bytes,int) or isinstance(max_bytes,bool) or max_bytes<1:raise ValueError('Définir une limite de téléchargement positive.')
    if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not np.isfinite(timeout) or timeout<=0:raise ValueError('Le délai de téléchargement doit être positif et fini.')
    if not isinstance(include_companions,bool):raise ValueError('include_companions doit être booléen.')
    remote=isinstance(source,str) and source.startswith(('https://','http://'))
    document=copy.deepcopy(source) if isinstance(source,dict) else _fetch_json(source,timeout=timeout) if remote else read_json(source)
    if not isinstance(document,dict):raise ValueError('Objet STAC Item ou FeatureCollection attendu.')
    items=document.get('features',[]) if document.get('type')=='FeatureCollection' else [document]
    if not isinstance(items,list):raise ValueError('La collection STAC doit contenir une liste de scènes.')
    if not items or len(items)>1000:raise ValueError('Sélectionner entre 1 et 1 000 scènes.')
    requested=[]
    for i,item in enumerate(items):
        _stac_item(item)
        family,_,_=_stac_profile(item)
        spectral_records=_spectral_assets(item,require_bands=False) if family else []
        if assets is None:
            keys=list(stac_asset_keys(item,include_quality=include_companions,include_saturation=include_companions)) if spectral_records else list(item['assets'])
        else:
            if isinstance(assets,str):raise ValueError('assets doit être une liste de clés, pas une chaîne.')
            keys=list(assets)
            if family and include_companions:
                records=[r for r in spectral_records if r['key'] in keys]
                if records:
                    quality,_,saturation=_mask_assets(item)
                    if quality is not None:keys.append(quality)
                    if saturation is not None:keys.append(saturation)
                    if family=='sentinel' and any(not _declares_calibration(r['numeric']) for r in records):
                        metadata=_product_metadata_key(item)
                        if metadata is not None:keys.append(metadata)
        keys=list(dict.fromkeys(keys))
        if not keys:raise ValueError('Aucun asset sélectionné.')
        for key in keys:
            if key not in item['assets']:raise ValueError('Asset absent : '+key)
            href=item['assets'][key]['href'];href=urljoin(str(source),href) if remote else href
            if urlsplit(href).scheme not in {'http','https'}:
                raise ValueError('Cet asset exige une URL HTTP(S) accessible ; configurer son accès ou sélectionner une variante HTTP : '+key)
            requested.append((i,key,_url(href)))
    destination=Path(destination).resolve();total=0;records=[];copies=copy.deepcopy(items)
    for item in copies:item['assets']={};item['links']=[]
    with new_directory(destination) as work:
        for number,(i,key,url) in enumerate(requested,1):
            _check_cancel(cancel);asset=items[i]['assets'][key];suffix=Path(urlsplit(url).path).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,8}',suffix):suffix='.bin'
            filename=f'{i:04d}_{number:05d}'+suffix;target=work/filename;digest=hashlib.sha256();size=0
            with urlopen(Request(url,headers={'User-Agent':'Cartomize'}),timeout=timeout) as response,open(target,'xb') as handle:
                declared=response.headers.get('Content-Length')
                if declared and total+int(declared)>max_bytes:raise ValueError('Limite de téléchargement dépassée.')
                while True:
                    # When Content-Length is unavailable, one byte beyond the
                    # remaining budget suffices to detect an oversized stream.
                    _check_cancel(cancel);chunk=response.read(min(1024*1024,max_bytes-total+1))
                    if not chunk:break
                    total+=len(chunk);size+=len(chunk)
                    if total>max_bytes:raise ValueError('Limite de téléchargement dépassée.')
                    digest.update(chunk);handle.write(chunk)
                if declared and size!=int(declared):raise ValueError('Asset téléchargé incomplet.')
            checksum=digest.hexdigest();expected=asset.get('file:checksum','')
            if expected.startswith('1220') and len(expected)==68 and checksum!=expected[4:]:raise ValueError('Empreinte SHA256 de l’asset incorrecte.')
            copies[i]['assets'][key]={**asset,'href':filename,'file:checksum':'1220'+checksum}
            records.append(dict(scene=items[i]['id'],asset=key,file=filename,bytes=size,sha256=checksum))
            if progress:progress(number,len(requested))
        save_json(dict(type='FeatureCollection',features=copies,links=[]),work/'scenes.json')
        save_json(dict(schema='cartomize.download.v1',bytes=total,assets=records),work/'download.json');_check_cancel(cancel)
    return destination/'scenes.json'
