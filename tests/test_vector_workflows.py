"""Regression tests for the vector operations exercised on external projects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import numpy as np
import pandas as pd
import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import Point, box
import pytest
import cartomize as cm


@pytest.fixture
def zones():
    return gpd.GeoDataFrame({'zone':['A','B','C']},geometry=[box(0,0,10,10),box(8,0,18,10),box(40,0,50,10)],crs=32631,index=[5,5,9])


@pytest.fixture
def points():
    return gpd.GeoDataFrame({'name':['a','b','c'], 'value':[1.,4.,np.nan]},geometry=[Point(2,2),Point(9,2),Point(10,10)],crs=32631)


@pytest.mark.parametrize('comparison,value,count',[('eq','a',1),('ne','a',2),('contains','b',1),('starts_with','c',1),('is_null',None,0),('not_null',None,3),('in',['a','c'],2),('not_in',['a','c'],1)])
def test_attribute_selection(points,comparison,value,count):
    result=cm.select_attributes(points,'name',comparison,value)
    assert len(result)==count and result.crs==points.crs
    assert len(points)==3


def test_literal_text_is_not_an_expression(points):
    assert cm.select_attributes(points,'name','contains','.*').empty
    with pytest.raises(ValueError):cm.select_attributes(points,'value','gt','not numeric')


def test_spatial_selection_does_not_duplicate_overlap(zones,points):
    result=cm.select_location(points,zones,predicate='within')
    assert result['name'].tolist()==['a','b']
    assert len(cm.select_location(points,zones,predicate='covered_by'))==3


def test_summary_preserves_duplicate_zone_indices_and_empty_zones(zones,points):
    result=cm.spatial_summary(zones,points,predicate='within',output_field='n')
    assert result.index.tolist()==[5,5,9]
    assert result['n'].tolist()==[2,1,0]
    assert len(zones.columns)==2
    actual=cm.spatial_summary(zones,points,field='value',statistic='sum',output_field='s')
    assert actual['s'].tolist()==[5.,4.,0.]


def test_summary_rejects_overwriting_attributes(zones,points):
    with pytest.raises(ValueError):cm.spatial_summary(zones,points,output_field='zone')
    with pytest.raises(ValueError):cm.spatial_summary(zones,points,field='name',statistic='mean')


def test_latest_record_preserves_missing_values(points):
    data=points.copy();data['site']=['A','A','B'];data['date']=['2020-01-01','2021-01-01','2021-01-01']
    data['value']=[42.,np.nan,8.]
    result=cm.latest_records(data,group_by='site',order_by='date')
    assert result['site'].tolist()==['A','B'] and pd.isna(result.iloc[0]['value'])
    assert result.iloc[0]['name']=='b'


def test_attribute_join_enforces_cardinality(points):
    duplicated=pd.DataFrame({'name':['a','a'],'population':[1,2]})
    with pytest.raises(pd.errors.MergeError):cm.join_attributes(points,duplicated,left_on='name')
    joined=cm.join_attributes(points,pd.DataFrame({'name':['a'],'population':[1]}),left_on='name')
    assert len(joined)==3 and joined.crs==points.crs


@pytest.mark.parametrize('operation',['centroid','representative_point','boundary','convex_hull','simplify','explode'])
def test_geometry_derivations_preserve_attributes(zones,operation):
    result=cm.geometry_operation(zones,operation,tolerance=1)
    assert result['zone'].tolist()==zones['zone'].tolist() and result.crs==zones.crs
    with pytest.raises(ValueError):cm.geometry_operation(zones,'unknown')


def test_desktop_uses_extended_vector_page_and_keeps_dissolve_identifier(tmp_path):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from cartomize.desktop import CartomizeWindow
    from cartomize.desktop_vector import VectorPage
    app=QApplication.instance() or QApplication([])
    window=CartomizeWindow()
    try:
        page=window.tool('vector');assert isinstance(page,VectorPage)
        assert all(page.operation.findData(key)>=0 for _,key in VectorPage.EXTRA)
        data=gpd.GeoDataFrame({'group':['A','A'],'population':[1,2]},geometry=[box(0,0,1,1),box(1,0,2,1)],crs=32631)
        source=tmp_path/'source.gpkg';destination=tmp_path/'dissolved.gpkg';data.to_file(source,index=False)
        page.operation.setCurrentIndex(page.operation.findData('dissolve'))
        page.source.edit.setText(str(source));page.field.setText('group');page.output.edit.setText(str(destination))
        page.refresh_fields();assert page.summary_field.findText('population')>=0
        page.job({'overwrite':False})(lambda *_:None,threading.Event())
        result=gpd.read_file(destination);assert result['group'].tolist()==['A']
        page.summary_field.setCurrentText('population');page.aggregation.setCurrentIndex(page.aggregation.findData('sum'))
        page.job({'overwrite':True})(lambda *_:None,threading.Event())
        result=gpd.read_file(destination);assert result['population'].tolist()==[3]
    finally:
        window.close();app.processEvents()
