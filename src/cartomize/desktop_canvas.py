"""Embedded geographic canvas with asynchronous, resolution-aware rendering."""
import math
from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import CRS, Geod, Transformer
from rasterio.warp import transform_bounds
from PySide6.QtCore import Qt, QObject, Signal, Slot, QRunnable, QThreadPool, QTimer, QRectF, QRect, QSize, QPointF
from PySide6.QtGui import QImage, QPixmap, QTransform, QPainter, QPainterPath, QPen, QColor, QImageReader
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from PySide6.QtSvgWidgets import QGraphicsSvgItem

from .viewer_data import (RASTERS, VECTORS, IMAGES, raster_info, vector_info, pdf_info,
                          render_raster, render_pdf, pixel_values, bounded_shape)

IO_POOL = QThreadPool()
IO_POOL.setMaxThreadCount(2)


class JobSignals(QObject):
    done = Signal(object, object, str)


class ReadJob(QRunnable):
    """No widget or open dataset crosses the worker-thread boundary."""
    def __init__(self, token, function):
        super().__init__(); self.token = token; self.function = function; self.signals = JobSignals()

    @Slot()
    def run(self):
        try: value, error = self.function(), ''
        except Exception as exc: value, error = None, str(exc)
        self.signals.done.emit(self.token, value, error)


def render_image(path, rect, shape):
    x, y, w, h = rect
    reader = QImageReader(str(path)); reader.setAutoTransform(True)
    reader.setClipRect(QRect(math.floor(x), math.floor(y), max(1, math.ceil(w)), max(1, math.ceil(h))))
    reader.setScaledSize(QSize(shape[1], shape[0]))
    image = reader.read()
    if image.isNull(): raise ValueError(reader.errorString())
    return dict(image=image, rect=rect, legend=[])


def render_vector(path, info, rect, shape):
    """Query only the visible extent and paint geometry in a worker-owned image."""
    import pyogrio
    x, y, w, h = rect; height, width = shape
    data = pyogrio.read_dataframe(path, layer=info.get('layer'), bbox=(x,-y-h,x+w,-y), max_features=40001)
    limited = len(data)>40000; data = data.iloc[:40000]
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied); image.fill(QColor('white'))
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tolerance = max(w/width, h/height)*.35
    classes = info.get('classes', {}); column = info.get('column')
    def point(coords): return QPointF((coords[0]-x)/w*width, (-coords[1]-y)/h*height)
    def geometry(geom, color):
        if geom is None or geom.is_empty: return
        kind = geom.geom_type
        if kind.startswith('Multi') or kind=='GeometryCollection':
            for part in geom.geoms: geometry(part, color)
        elif kind=='Point':
            painter.setBrush(QColor(color)); painter.setPen(QPen(QColor('#ffffff'), .8)); painter.drawEllipse(point(geom.coords[0]), 3.5, 3.5)
        elif kind in {'Polygon', 'LineString', 'LinearRing'}:
            geom = geom.simplify(tolerance, preserve_topology=True)
            path = QPainterPath(); path.setFillRule(Qt.FillRule.OddEvenFill)
            rings = [geom.exterior, *geom.interiors] if geom.geom_type=='Polygon' else [geom]
            for ring in rings:
                coordinates = list(ring.coords)
                if not coordinates: continue
                path.moveTo(point(coordinates[0]))
                for coords in coordinates[1:]: path.lineTo(point(coords))
                if geom.geom_type=='Polygon': path.closeSubpath()
            painter.setPen(QPen(QColor('#394f45') if kind=='Polygon' else QColor(color), .9 if kind=='Polygon' else 1.5))
            fill = QColor(color); fill.setAlpha(115)
            painter.setBrush(fill if kind=='Polygon' else Qt.BrushStyle.NoBrush); painter.drawPath(path)
    try:
        for _, row in data.iterrows():
            value = row.get(column) if column else None
            entry = classes.get(value, classes.get(str(value)))
            geometry(row.geometry, entry[1] if entry else info.get('color') or '#46695a')
    finally: painter.end()
    legend = [(v[0], v[1], k) for k,v in classes.items()] or [(Path(path).stem, info.get('color') or '#46695a', None)]
    return dict(image=image, rect=rect, legend=legend,
                warning='Aperçu limité à 40 000 entités visibles : zoomer pour consulter une zone plus petite.' if limited else '')


class GeoCanvas(QGraphicsView):
    rendered = Signal(object)
    error = Signal(str)
    position = Signal(str)
    identified = Signal(str)
    extentChanged = Signal(object, object)

    def __init__(self, path, options=None, parent=None):
        super().__init__(parent)
        self.path = str(Path(path).resolve()); self.options = dict(options or {})
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene); self.setBackgroundBrush(QColor('#eceeec'))
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True); self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._generation=0; self._serial=0; self._busy=False; self._closed=False; self._mute=False
        self._fitted=True; self._want_overview=True; self._overview=None; self._detail=None; self.last_render=None
        self._timer=QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self._request)
        self._job=None; self._pixel_job=None; self._pixel_serial=0; self._press=None
        self.palette_name='viridis'; self.bands=(1,); self.limits=None; self.resampling='nearest'; self.page=0
        self.info=self._information(); self.kind=self.info['kind']
        self._affine=Affine(*self.info['transform']) if self.kind=='raster' else None
        self._to_geo=None; self._from_geo=None; self._geod=Geod(ellps='WGS84')
        if self.info.get('crs'):
            self._to_geo=Transformer.from_crs(self.info['crs'],4326,always_xy=True)
            self._from_geo=Transformer.from_crs(4326,self.info['crs'],always_xy=True)
        if self.kind=='raster':
            self.bands=tuple(self.info['rgb']) if self.info.get('rgb') and not self.info['classes'] else (1,)
            self._default_limits()
        if self.kind=='svg':
            self._svg=QGraphicsSvgItem(self.path)
            if not self._svg.renderer().isValid(): raise ValueError('Document SVG illisible.')
            self._svg.setCacheMode(QGraphicsSvgItem.CacheMode.NoCache)
            self.scene().addItem(self._svg); self.scene().setSceneRect(self._svg.boundingRect())
        else: self._reset_scene_rect()
        self.horizontalScrollBar().valueChanged.connect(self._changed)
        self.verticalScrollBar().valueChanged.connect(self._changed)
        QTimer.singleShot(0,self.fit_extent)

    def _information(self):
        suffix=Path(self.path).suffix.lower()
        if suffix in RASTERS: return raster_info(self.path,self.options)
        if suffix in VECTORS: return vector_info(self.path,self.options)
        if suffix=='.pdf': return pdf_info(self.path)
        if suffix=='.svg': return dict(kind='svg',path=self.path,crs=None)
        if suffix in IMAGES:
            reader=QImageReader(self.path); size=reader.size()
            if not size.isValid(): raise ValueError(reader.errorString())
            return dict(kind='image',path=self.path,width=size.width(),height=size.height(),crs=None)
        raise ValueError('Ce fichier ne contient pas une vue cartographique prise en charge.')

    def _reset_scene_rect(self):
        if self.kind=='vector':
            a,b,c,d=self.info['bounds']; self.scene().setSceneRect(QRectF(a,-d,c-a,d-b))
        else:
            w,h=self.info['sizes'][self.page] if self.kind=='pdf' else (self.info['width'],self.info['height'])
            self.scene().setSceneRect(QRectF(0,0,w,h))

    def _default_limits(self):
        self.limits=None
        if self.kind=='raster' and len(self.bands)==1:
            semantic=self.info['descriptions'][self.bands[0]-1].upper()
            if semantic in {'NDVI','NDMI','NDWI','MNDWI','NBR','NBR2','GNDVI'}:
                self.limits=((-1.,1.),); self.palette_name='RdYlGn'

    def set_style(self, *, bands=None, palette=None, resampling=None):
        if bands is not None: self.bands=tuple(bands); self._default_limits()
        if palette: self.palette_name=palette
        if resampling: self.resampling=resampling
        self.refresh()

    def set_page(self, page):
        if self.kind!='pdf' or page==self.page: return
        self.page=page; self._reset_scene_rect(); self.refresh(); self.fit_extent()

    def refresh(self):
        self._generation+=1; self._want_overview=True
        if self.kind=='svg':
            self._svg.renderer().load(self.path); self.scene().setSceneRect(self._svg.boundingRect())
        for name in ('_overview','_detail'):
            item=getattr(self,name)
            if item is not None: self.scene().removeItem(item); setattr(self,name,None)
        self._changed()

    def fit_extent(self):
        if self._closed: return
        self._mute=True; self.fitInView(self.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio); self._mute=False
        self._fitted=True; self._changed()

    def native_scale(self):
        self._fitted=False; self._mute=True; self.resetTransform(); self._mute=False; self._changed()

    def zoom(self,factor):
        baseline=min(self.viewport().width()/max(self.sceneRect().width(),1e-12),self.viewport().height()/max(self.sceneRect().height(),1e-12))
        ratio=self.transform().m11()*factor/max(baseline,1e-12)
        if not .05<=ratio<=1e6: return
        self._fitted=False; self._mute=True; self.scale(factor,factor); self._mute=False; self._changed()

    def wheelEvent(self,event):
        self.zoom(1.3**(event.angleDelta().y()/120)); event.accept()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'_fitted'):
            if self._fitted: self.fit_extent()
            else: self._changed()

    def showEvent(self,event):
        super().showEvent(event)
        if self._fitted: self.fit_extent()
        else: self._changed()

    def _changed(self,*args):
        if self._closed or self._mute: return
        self._serial+=1; self._timer.start(75); self.viewport().update()
        extent=self.geographic_extent()
        if extent is not None: self.extentChanged.emit(extent,self.info['crs'])

    def _request(self):
        if self._closed or self._busy or self.kind=='svg': return
        overview=self._want_overview
        rect=self.sceneRect() if overview else self.mapToScene(self.viewport().rect()).boundingRect().intersected(self.sceneRect())
        if rect.isEmpty(): return
        if overview:
            size=bounded_shape(rect.width(),rect.height(),maximum=900,pixels=810000)
            if self.kind=='vector': size=bounded_shape(900,900*rect.height()/rect.width(),maximum=900,pixels=810000)
        else:
            scale=self.transform().m11()*self.devicePixelRatioF()
            size=bounded_shape(rect.width()*scale,rect.height()*scale)
        box=(rect.x(),rect.y(),rect.width(),rect.height())
        generation,serial=self._generation,self._serial
        path=self.path; kind=self.kind; page=self.page; info=dict(self.info)
        bands=tuple(self.bands); palette=self.palette_name; limits=self.limits; resampling=self.resampling
        def read():
            if kind=='raster': return render_raster(path,box,size,bands,palette,info['classes'] if len(bands)==1 else None,limits,resampling)
            if kind=='vector': return render_vector(path,info,box,size)
            if kind=='pdf': return render_pdf(path,page,box,size)
            return render_image(path,box,size)
        self._busy=True; self._job=ReadJob((generation,serial,overview),read)
        self._job.signals.done.connect(self._accept); IO_POOL.start(self._job)

    @Slot(object,object,str)
    def _accept(self,token,result,error):
        self._busy=False
        if self._closed: return
        generation,serial,overview=token
        if generation==self._generation:
            if overview: self._want_overview=False
            if error: self.error.emit(error)
            elif overview or serial==self._serial:
                if 'image' in result: image=result['image']
                else:
                    array=result['rgba']; h,w,_=array.shape
                    image=QImage(array.data,w,h,array.strides[0],QImage.Format.Format_RGBA8888).copy()
                pixmap=QPixmap.fromImage(image)
                name='_overview' if overview else '_detail'; item=getattr(self,name)
                if item is None:
                    item=QGraphicsPixmapItem(); item.setZValue(0 if overview else 1); self.scene().addItem(item); setattr(self,name,item)
                item.setPixmap(pixmap); x,y,w,h=result['rect']; item.setPos(x,y)
                item.setTransform(QTransform.fromScale(w/pixmap.width(),h/pixmap.height()))
                nearest=self.kind=='raster' and (bool(self.info.get('classes')) or self.resampling=='nearest')
                item.setTransformationMode(Qt.TransformationMode.FastTransformation if nearest else Qt.TransformationMode.SmoothTransformation)
                self.last_render=result; self.rendered.emit(result)
        if overview or serial!=self._serial or generation!=self._generation: self._timer.start(0)

    def scene_to_world(self,point):
        if self._affine:
            a=self._affine; x,y=point.x(),point.y(); return a.a*x+a.b*y+a.c,a.d*x+a.e*y+a.f
        return point.x(),-point.y()

    def world_to_scene(self,x,y):
        if self._affine:
            a=~self._affine; return QPointF(a.a*x+a.b*y+a.c,a.d*x+a.e*y+a.f)
        return QPointF(x,-y)

    def geographic_extent(self):
        if not self.info.get('crs'): return None
        polygon=self.mapToScene(self.viewport().rect()); values=[self.scene_to_world(p) for p in polygon]
        if not values: return None
        xs,ys=zip(*values); return (min(xs),min(ys),max(xs),max(ys))

    def set_geographic_extent(self,extent,crs):
        if extent is None or not self.info.get('crs') or not crs: return False
        if CRS.from_user_input(crs)!=CRS.from_user_input(self.info['crs']):
            extent=transform_bounds(crs,self.info['crs'],*extent,densify_pts=21)
        if not np.isfinite(extent).all(): return False
        xmin,ymin,xmax,ymax=extent
        points=[self.world_to_scene(x,y) for x,y in [(xmin,ymin),(xmin,ymax),(xmax,ymin),(xmax,ymax)]]
        xs=[p.x() for p in points]; ys=[p.y() for p in points]
        rect=QRectF(min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys))
        if rect.isEmpty(): return False
        self._mute=True; self.fitInView(rect,Qt.AspectRatioMode.KeepAspectRatio); self._mute=False
        self._fitted=False; self._serial+=1; self._timer.start(75); self.viewport().update(); return True

    def mousePressEvent(self,event):
        self._press=event.position(); super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        super().mouseMoveEvent(event)
        p=self.mapToScene(event.position().toPoint())
        if self.info.get('crs'):
            x,y=self.scene_to_world(p); self.position.emit(f'X {x:.3f}   Y {y:.3f}   ·   {self.info["crs"]}')
        else: self.position.emit(f'Position {p.x():.1f}, {p.y():.1f} · document sans SCR')

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if self._press is not None and (event.position()-self._press).manhattanLength()<4 and self.kind=='raster':
            self.identify(self.mapToScene(event.position().toPoint()))
        self._press=None; self._changed()

    def identify(self,point):
        if self._closed: return
        self._pixel_serial+=1; path=self.path; col,row=math.floor(point.x()),math.floor(point.y()); bands=tuple(self.bands)
        self._pixel_job=ReadJob((self._pixel_serial,col,row,bands),lambda:pixel_values(path,col,row,bands))
        self._pixel_job.signals.done.connect(self._identified); IO_POOL.start(self._pixel_job,1)

    @Slot(object,object,str)
    def _identified(self,token,values,error):
        if self._closed or token[0]!=self._pixel_serial: return
        if error: self.error.emit(error); return
        if values is None: self.identified.emit('Position hors du raster.'); return
        _,col,row,bands=token
        parts=[f'{self.info["descriptions"][band-1]} : '+('NoData' if value is None else f'{value:.8g}') for band,value in zip(bands,values)]
        if len(values)==1 and values[0] in self.info.get('classes',{}): parts.append(str(self.info['classes'][values[0]][0]))
        self.identified.emit(f'Colonne {col} · ligne {row} — '+' ; '.join(parts))

    def drawForeground(self,painter,rect):
        super().drawForeground(painter,rect)
        if not self._to_geo: return
        try:
            center=self.viewport().rect().center(); a=self.mapToScene(center); b=self.mapToScene(center.x()+100,center.y())
            lon,lat=self._to_geo.transform(*self.scene_to_world(a)); lon2,lat2=self._to_geo.transform(*self.scene_to_world(b))
            _,_,distance=self._geod.inv(lon,lat,lon2,lat2)
            if not math.isfinite(distance) or distance<=0: return
            base=10**math.floor(math.log10(distance)); value=max(v for v in (.1*base,.2*base,.5*base,base,2*base,5*base) if v<=distance)
            length=100*value/distance; y=self.viewport().height()-30
            painter.save(); painter.resetTransform(); painter.setPen(QPen(QColor('#202820'),2))
            painter.fillRect(QRectF(10,y-22,max(length+25,130),42),QColor(255,255,255,225))
            painter.drawLine(QPointF(20,y),QPointF(20+length,y)); painter.drawLine(QPointF(20,y-4),QPointF(20,y+4)); painter.drawLine(QPointF(20+length,y-4),QPointF(20+length,y+4))
            label=f'≈ {value/1000:g} km' if value>=1000 else f'≈ {value:g} m'; painter.drawText(QPointF(20,y-8),label)
            northlon,northlat,_=self._geod.fwd(lon,lat,0,max(10,distance))
            north=self.mapFromScene(self.world_to_scene(*self._from_geo.transform(northlon,northlat)))
            dx,dy=north.x()-center.x(),north.y()-center.y(); norm=math.hypot(dx,dy)
            if norm:
                start=QPointF(self.viewport().width()-32,58); end=start+QPointF(dx/norm*24,dy/norm*24)
                painter.drawLine(start,end)
                for sign in (-1,1): painter.drawLine(end,end-QPointF(dx/norm*7,dy/norm*7)+QPointF(-dy/norm*4*sign,dx/norm*4*sign))
                painter.drawText(end+QPointF(-4,-5),'N')
            painter.restore()
        except (ValueError,OverflowError): pass

    def capture(self):
        rect=self.mapToScene(self.viewport().rect()).boundingRect()
        return dict(path=self.path,options=self.options,bands=list(self.bands),palette=self.palette_name,
                    resampling=self.resampling,page=self.page,rect=[rect.x(),rect.y(),rect.width(),rect.height()],fitted=self._fitted)

    def restore(self,state):
        if self.kind=='pdf': self.page=min(state.get('page',0),self.info['pages']-1); self._reset_scene_rect()
        bands=tuple(state.get('bands',self.bands))
        if self.kind!='raster' or (len(bands) in {1,3} and all(type(i) is int and 1<=i<=self.info['count'] for i in bands)): self.bands=bands
        self._default_limits()
        self.palette_name=state.get('palette',self.palette_name); self.resampling=state.get('resampling','nearest')
        if not state.get('fitted',True) and state.get('rect'):
            self._mute=True; self.fitInView(QRectF(*state['rect']),Qt.AspectRatioMode.KeepAspectRatio); self._mute=False; self._fitted=False
        else: self.fit_extent()
        self.refresh()

    def dispose(self):
        if self._closed: return
        self._closed=True; self._generation+=1; self._pixel_serial+=1; self._timer.stop()
        # Detach and release the scene on the GUI event loop. Python cycles in
        # controls/comparisons must not determine when its native items die.
        self.setScene(None)
        self._scene.clear(); self._scene.deleteLater()
        self._overview=None; self._detail=None; self.last_render=None
