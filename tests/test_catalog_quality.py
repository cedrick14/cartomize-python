"""Scientific contracts for STAC downloads, masks and optical calibration."""
import copy
import io
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from shapely.geometry import box, mapping

import cartomize as cm
from cartomize import catalogs


def optical_item(family='sentinel'):
    return {
        'type':'Feature', 'stac_version':'1.0.0', 'id':'observation',
        'collection':'sentinel-2-l2a' if family=='sentinel' else 'landsat-c2-l2',
        'properties':{'platform':'Sentinel-2C' if family=='sentinel' else 'landsat-9',
                      'datetime':'2026-10-01T10:30:00Z'},
        'assets':{}, 'links':[],
    }


def spectral(path,name,common,*,scale=.0001,offset=-.1):
    asset={'href':str(path),'eo:bands':[{'name':name,'common_name':common}],
           'roles':['data'],'raster:bands':[{'nodata':0}]}
    if scale is not None:asset['raster:bands'][0].update(scale=scale,offset=offset)
    return asset


def fake_transport(monkeypatch,files):
    calls=[]
    class Response(io.BytesIO):
        def __init__(self,data):
            super().__init__(data)
            self.headers={'Content-Length':str(len(data))}
    def fetch(request,timeout):
        calls.append(request.full_url)
        return Response(files[request.full_url])
    monkeypatch.setattr(catalogs,'urlopen',fetch)
    return calls


def test_landsat_selected_download_keeps_quality_and_saturation(write_raster,tmp_path,monkeypatch):
    red=write_raster('red.tif',np.full((3,3),10000,dtype='uint16'),nodata=0)
    nir=write_raster('nir.tif',np.full((3,3),20000,dtype='uint16'),nodata=0)
    qa_values=np.zeros((3,3),dtype='uint16');qa_values[0,0]=8
    saturation_values=np.zeros((3,3),dtype='uint16');saturation_values[0,1]=1
    qa=write_raster('qa.tif',qa_values,nodata=None)
    saturation=write_raster('saturation.tif',saturation_values,nodata=None)
    item=optical_item('landsat')
    item['assets']={
        'red':spectral('https://imagery.invalid/red.tif','OLI_B4','red',scale=.0000275,offset=-.2),
        'nir08':spectral('https://imagery.invalid/nir.tif','OLI_B5','nir08',scale=.0000275,offset=-.2),
        'qa_pixel':{'href':'https://imagery.invalid/qa.tif','roles':['cloud']},
        'qa_radsat':{'href':'https://imagery.invalid/saturation.tif','roles':['saturation']},
    }
    calls=fake_transport(monkeypatch,{'https://imagery.invalid/'+p.name:p.read_bytes() for p in [red,nir,qa,saturation]})
    manifest=catalogs.download_stac(item,tmp_path/'download',assets=['red','nir08'])
    assert len(calls)==4
    scene=cm.discover_scenes(manifest)[0]
    assert (scene.sensor,scene.level,scene.quality_kind)==('landsat-9','C2-L2-SR','landsat_qa')
    assert scene.quality.is_file() and scene.saturation.is_file()
    result=cm.prepare_imagery([scene],tmp_path/'mosaic.tif',band_order=['red','nir'])
    with rasterio.open(result.path) as source:
        values=source.read(masked=True)
        assert values[0].count()==7
        assert values.mask[:,0,:2].all()
        np.testing.assert_allclose(values[0].compressed(),.075,rtol=1e-6)
        np.testing.assert_allclose(values[1].compressed(),.35,rtol=1e-6)
    assert json.loads(manifest.read_text())['features'][0]['assets']['red']['raster:bands'][0]['offset']==-.2


def test_sentinel_native_roles_do_not_collapse_red_edges_or_narrow_nir(write_raster):
    image=write_raster('spectral.tif',np.full((2,2),3000,dtype='uint16'),nodata=0)
    qa=write_raster('scl.tif',np.full((2,2),4,dtype='uint8'),nodata=0)
    item=optical_item()
    codes=[('rededge1','B05','rededge'),('rededge2','B06','rededge'),('rededge3','B07','rededge'),
           ('nir','B08','nir'),('nir08','B8A','nir08'),('nir09','B09','nir09')]
    item['assets']={key:spectral(image,code,common) for key,code,common in codes}
    item['assets']['scl']={'href':str(qa)}
    item['assets']['visual']={'href':'not-downloaded.tif','roles':['visual'],
                             'eo:bands':[{'name':'B04','common_name':'red'}]}
    scene=catalogs.scene_from_stac(item)
    assert set(scene.bands)=={'rededge1','rededge2','rededge3','nir','nir_narrow','water_vapour'}
    assert scene.sensor=='sentinel-2' and scene.level=='L2A-SR'
    assert scene.quality_kind=='sentinel_scl'


def test_earth_search_prefers_cog_and_retains_calibration_for_download(monkeypatch,write_raster,tmp_path):
    image=write_raster('data.tif',np.full((2,2),5000,dtype='uint16'),nodata=0)
    qa=write_raster('scl.tif',np.full((2,2),4,dtype='uint8'),nodata=0)
    item=optical_item()
    for key,code,common in [('red','B04','red'),('nir','B08','nir'),('nir08','B8A','nir08')]:
        item['assets'][key]=spectral('https://imagery.invalid/'+key+'.tif',code,common)
        alternate=copy.deepcopy(item['assets'][key]);alternate['href']='s3://restricted/'+code+'.jp2'
        item['assets'][key+'-jp2']=alternate
    item['assets']['scl']={'href':'https://imagery.invalid/scl.tif'}
    item['assets']['scl-jp2']={'href':'s3://restricted/SCL.jp2'}
    item['assets']['visual']={'href':'https://imagery.invalid/visual.tif','roles':['visual']}
    assert catalogs.stac_asset_keys(item,band_order=['red','nir'])==('red','nir','scl')
    calls=fake_transport(monkeypatch,{**{'https://imagery.invalid/'+k+'.tif':image.read_bytes() for k in ('red','nir','nir08')},
                                     'https://imagery.invalid/scl.tif':qa.read_bytes()})
    manifest=catalogs.download_stac(item,tmp_path/'earthsearch')
    assert len(calls)==4
    scene=catalogs.load_scenes_manifest(manifest)[0]
    assert set(scene.bands)=={'red','nir','nir_narrow'}
    assert scene.bands['red'].offset==-.1


def test_sentinel_xml_companion_calibrates_downloaded_bands(write_raster,tmp_path,monkeypatch):
    red=write_raster('red.tif',np.full((2,2),3000,dtype='uint16'),nodata=0)
    nir=write_raster('nir.tif',np.full((2,2),5000,dtype='uint16'),nodata=0)
    qa=write_raster('scl.tif',np.array([[4,9],[4,4]],dtype='uint8'),nodata=0)
    xml=b'<Product><PROCESSING_BASELINE>05.13</PROCESSING_BASELINE><BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE><BOA_ADD_OFFSET band_id="3">-1000</BOA_ADD_OFFSET><BOA_ADD_OFFSET band_id="7">-1000</BOA_ADD_OFFSET></Product>'
    item=optical_item();item['assets']={
        'B04':spectral('https://imagery.invalid/red.tif','B04','red',scale=None),
        'B08':spectral('https://imagery.invalid/nir.tif','B08','nir',scale=None),
        'SCL':{'href':'https://imagery.invalid/scl.tif'},
        'product-metadata':{'href':'https://imagery.invalid/MTD_MSIL2A.xml','roles':['metadata']},
    }
    calls=fake_transport(monkeypatch,{**{'https://imagery.invalid/'+p.name:p.read_bytes() for p in [red,nir,qa]},
                                     'https://imagery.invalid/MTD_MSIL2A.xml':xml})
    keys=catalogs.stac_asset_keys(item,band_order=['red','nir'])
    assert set(keys)=={'B04','B08','SCL','product-metadata'}
    manifest=catalogs.download_stac(item,tmp_path/'sentinel',assets=['B04','B08'])
    assert len(calls)==4
    scene=catalogs.load_scenes_manifest(manifest)[0]
    result=cm.prepare_imagery([scene],tmp_path/'sentinel_mosaic.tif')
    with rasterio.open(result.path) as source:
        values=source.read(masked=True)
        assert values[0].count()==3
        np.testing.assert_allclose(values[0].compressed(),.2,rtol=1e-6)
        np.testing.assert_allclose(values[1].compressed(),.4,rtol=1e-6)


@pytest.mark.parametrize('metadata',[None,'<Product><BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE><PROCESSING_BASELINE>05.00</PROCESSING_BASELINE></Product>'])
def test_missing_sentinel_calibration_is_never_assumed(write_raster,tmp_path,metadata):
    image=write_raster('band.tif',np.ones((2,2),dtype='uint16'),nodata=0)
    item=optical_item();item['assets']['B04']=spectral(image,'B04','red',scale=None)
    if metadata is not None:
        file=tmp_path/'metadata.xml';file.write_text(metadata)
        item['assets']['product-metadata']={'href':str(file),'roles':['metadata']}
    with pytest.raises(ValueError,match='Calibration Sentinel absente|BOA_ADD_OFFSET absent'):
        catalogs.scene_from_stac(item)


def test_sentinel_explicit_stac_calibration_does_not_apply_xml_twice(write_raster):
    image=write_raster('physical.tif',np.full((2,2),.4,dtype='float32'),nodata=None)
    item=optical_item();item['assets']['B04']=spectral(image,'B04','red',scale=1,offset=0)
    item['assets']['product-metadata']={'href':'unneeded.xml','roles':['metadata']}
    scene=catalogs.scene_from_stac(item)
    assert scene.bands['red'].scale==1 and scene.bands['red'].offset==0


def test_sentinel_can_use_explicit_raster_scale_offset(write_raster):
    image=write_raster('scaled.tif',np.full((2,2),3000,dtype='uint16'),nodata=0)
    with rasterio.open(image,'r+') as dst:dst.scales=(.0001,);dst.offsets=(-.1,)
    item=optical_item();item['assets']['B04']=spectral(image,'B04','red',scale=None)
    scene=catalogs.scene_from_stac(item)
    assert (scene.bands['red'].scale,scene.bands['red'].offset)==(.0001,-.1)


@pytest.mark.parametrize('flag,collection,asset_key,media,effective',[
    (True,'sentinel-2-l2a','red','image/tiff; application=geotiff; profile=cloud-optimized',0.),
    (False,'sentinel-2-l2a','red','image/tiff',-.1),
    (True,'sentinel-2-l2a','red-jp2','image/jp2',-.1),
    (True,'sentinel-2-c1-l2a','red','image/tiff',-.1),
    ('true','sentinel-2-l2a','red','image/tiff',-.1),
])
def test_harmonized_earthsearch_cog_does_not_apply_boa_offset_twice(write_raster,flag,collection,asset_key,media,effective):
    image=write_raster('harmonized.tif',np.full((2,2),700,dtype='uint16'),nodata=0)
    item=optical_item();item['collection']=collection
    item['properties'].update({'earthsearch:boa_offset_applied':flag,'s2:product_type':'S2MSI2A'})
    item['assets'][asset_key]={**spectral(image,'B04','red'), 'type':media}
    before=copy.deepcopy(item)
    scene=catalogs.scene_from_stac(item)
    assert scene.bands['red'].offset==effective
    assert scene.bands['red'].scale==.0001
    assert item==before
    if effective==0:assert 'offset déclaré=-0.1, offset effectif=0' in scene.notes[-1]


def test_custom_quality_mapping_survives_manifest_load(write_raster,tmp_path):
    image=write_raster('custom.tif',np.full((2,2),10,dtype='int16'))
    valid=write_raster('valid.tif',np.array([[.25,0],[1,1]],dtype='float32'),nodata=None)
    item=optical_item();item['collection']='custom';item['properties']['platform']='custom'
    item['assets']={'signal':{'href':str(image),'raster:bands':[{'scale':.1,'offset':0,'nodata':'-9999'}]},
                    'mask':{'href':str(valid)}}
    file=tmp_path/'custom.json';file.write_text(json.dumps(item))
    options={'band_mapping':{'signal':'red'},'quality_asset':'mask','quality_kind':'valid_mask'}
    assert catalogs.stac_asset_keys(item,band_order=['red'],**options)==('signal','mask')
    scene=catalogs.load_scenes_manifest(file,**options)[0]
    assert scene.bands['red'].nodata==-9999
    result=cm.prepare_imagery([scene],tmp_path/'custom_output.tif')
    with rasterio.open(result.path) as src:assert src.read(1,masked=True).count()==3


def test_unknown_product_does_not_guess_scl_semantics(write_raster):
    image=write_raster('unknown.tif',np.ones((2,2),dtype='float32'))
    item=optical_item();item['collection']='another-product';item['properties']['platform']='another-sensor'
    item['assets']={'red':spectral(image,'band1','red'),'scl':{'href':str(image)}}
    scene=catalogs.scene_from_stac(item)
    assert scene.quality is None
    with pytest.raises(ValueError,match='Aucun masque QA/SCL'):
        catalogs.stac_asset_keys(item)
    assert catalogs.stac_asset_keys(item,include_quality=False)==('red',)


def test_quality_asset_must_be_local_and_present(write_raster):
    image=write_raster('signal.tif',np.ones((2,2),dtype='float32'))
    item=optical_item();item['assets']={'red':spectral(image,'B04','red'),'scl':{'href':'https://imagery.invalid/SCL.tif'}}
    with pytest.raises(ValueError,match='Télécharger les assets'):catalogs.scene_from_stac(item)
    item['assets']['scl']['href']='missing.tif'
    with pytest.raises(FileNotFoundError):catalogs.scene_from_stac(item)


def test_custom_duplicate_roles_and_visual_mapping_are_explicit_errors(write_raster):
    image=write_raster('signal.tif',np.ones((2,2),dtype='float32'))
    item=optical_item();item['collection']='custom';item['properties']['platform']='custom'
    item['assets']={'first':spectral(image,'band','red'),'second':spectral(image,'band','red')}
    with pytest.raises(ValueError,match='même rôle'):catalogs.scene_from_stac(item)
    item['assets']={'visual':{'href':str(image),'roles':['visual']}}
    with pytest.raises(ValueError,match='composition visuelle'):
        catalogs.stac_asset_keys(item,band_mapping={'visual':'red'},include_quality=False)


def test_polygon_search_posts_geometry_and_preserves_merged_pagination(monkeypatch):
    calls=[]
    first=optical_item();first['id']='first';first['assets']={'red':{'href':'red.tif'}}
    second=copy.deepcopy(first);second['id']='second'
    def fetch(url,*,body=None,timeout=60):
        calls.append((url,body,timeout))
        return {'type':'FeatureCollection','features':[first if len(calls)==1 else second],
                'links':[{'rel':'next','href':'./search','method':'POST','body':{'token':'next'},'merge':True}] if len(calls)==1 else []}
    monkeypatch.setattr(catalogs,'_fetch_json',fetch)
    geometry=mapping(box(10,-5,11,-4))
    result=catalogs.search_stac('https://catalog.invalid/v1/search',intersects=geometry,
                              collections=['sentinel-2-l2a'],datetime_range='2026-01-01/2026-02-01',limit=2,timeout=17)
    assert [x['id'] for x in result['features']]==['first','second']
    assert calls[0][0]=='https://catalog.invalid/v1/search'
    assert calls[0][1]['intersects']==geometry and calls[0][1]['collections']==['sentinel-2-l2a']
    assert calls[1][1]['token']=='next' and calls[1][1]['intersects']==geometry
    assert calls[1][2]==17
    assert result['features'][0]['assets']['red']['href']=='https://catalog.invalid/v1/red.tif'


@pytest.mark.parametrize('parameters',[
    {'bbox':[10,-5,11,-4],'intersects':mapping(box(10,-5,11,-4))},
    {'intersects':mapping(box(1000,10,1010,20))},
    {'intersects':{'type':'Polygon','coordinates':[]}},
    {'timeout':0}, {'limit':True}, {'collections':'sentinel-2-l2a'},
])
def test_invalid_search_parameters_do_not_request_network(monkeypatch,parameters):
    monkeypatch.setattr(catalogs,'_fetch_json',lambda *args,**kwargs:pytest.fail('invalid request reached network'))
    with pytest.raises(ValueError):catalogs.search_stac('https://catalog.invalid',**parameters)


@pytest.mark.parametrize('change',[{'id':['not','hashable']},{'collection':['not','hashable']},{'assets':{'red':[]}}, {'links':[None]}])
def test_malformed_stac_items_raise_explained_errors(monkeypatch,change):
    item=optical_item();item['assets']={'red':{'href':'red.tif'}};item.update(change)
    monkeypatch.setattr(catalogs,'_fetch_json',lambda *args,**kwargs:{'type':'FeatureCollection','features':[item],'links':[]})
    with pytest.raises(ValueError,match='STAC'):
        catalogs.search_stac('https://catalog.invalid')


def test_download_companions_can_be_explicitly_disabled(write_raster,tmp_path,monkeypatch):
    image=write_raster('red.tif',np.ones((2,2),dtype='uint16'),nodata=0)
    item=optical_item();item['assets']={'red':spectral('https://imagery.invalid/red.tif','B04','red'),
                                      'scl':{'href':'https://imagery.invalid/scl.tif'}}
    calls=fake_transport(monkeypatch,{'https://imagery.invalid/red.tif':image.read_bytes()})
    manifest=catalogs.download_stac(item,tmp_path/'spectral_only',assets=['red'],include_companions=False)
    assert calls==['https://imagery.invalid/red.tif']
    assert catalogs.load_scenes_manifest(manifest)[0].quality is None


def test_explicit_quality_only_download_remains_supported(tmp_path,monkeypatch):
    item=optical_item();item['assets']={'SCL':{'href':'https://imagery.invalid/scl.tif'}}
    calls=fake_transport(monkeypatch,{'https://imagery.invalid/scl.tif':b'quality-only'})
    manifest=catalogs.download_stac(item,tmp_path/'qa_only',assets=['SCL'])
    assert calls==['https://imagery.invalid/scl.tif']
    assert set(json.loads(manifest.read_text())['features'][0]['assets'])=={'SCL'}


def test_unknown_length_download_reads_only_remaining_budget(tmp_path,monkeypatch):
    received=[]
    class Response(io.BytesIO):
        headers={}
        def read(self,size=-1):
            data=super().read(size);received.append(len(data));return data
    monkeypatch.setattr(catalogs,'urlopen',lambda request,timeout:Response(b'x'*1_000_000))
    item=optical_item();item['collection']='custom';item['properties']['platform']='custom'
    item['assets']={'data':{'href':'https://imagery.invalid/data.tif'}}
    with pytest.raises(ValueError,match='Limite de téléchargement'):
        catalogs.download_stac(item,tmp_path/'over_budget',max_bytes=100)
    assert sum(received)==101
    assert not (tmp_path/'over_budget').exists()
