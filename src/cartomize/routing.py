"""Metric shortest paths on noded line networks using Dijkstra's algorithm."""
import heapq
import numpy as np
import geopandas as gpd
from shapely import STRtree
from shapely.geometry import Point,LineString
from shapely.ops import unary_union
from scipy.spatial import cKDTree
from ._validation import frame,measurement_frame
from .imagery import _check_cancel


def shortest_path(source,start,end,*,points_crs=None,metric_crs=None,max_snap_m=1000.,
                  node_intersections=True,snap='edge',progress=None,cancel=None):
    """Shortest distance on an undirected network, with explicit attachment.

    Coordinates default to the network CRS. Lines are split at vertices and,
    optionally, geometric intersections. Bridges at different levels require
    node_intersections=False and an already topologically prepared network.
    ``snap='edge'`` projects each point to its nearest positive-length segment;
    equal-distance ties use the first segment in canonical coordinate order.
    Both projections split their chosen segments together. Interior attachment
    nodes belong only to that segment, even if another segment shares their XY.
    ``snap='node'`` retains attachment to existing network vertices.

    max_snap_m bounds attachment distances, reported separately and excluded
    from distance_m. Coincident network endpoints produce a valid Point with
    route_status='coincident'; other routes are LineStrings with status 'ok'.
    Outputs retain the source CRS and report snap_method.
    No turn restrictions or travel-time assumptions are inferred.
    """
    _check_cancel(cancel)
    if snap not in {'edge','node'}:raise ValueError("snap doit valoir 'edge' ou 'node'.")
    original=frame(source);work,factor=measurement_frame(original,metric_crs)
    if work.empty or not work.geom_type.isin(['LineString','MultiLineString']).all():raise ValueError('Le réseau doit contenir des lignes.')
    if work.geometry.isna().any() or work.geometry.is_empty.any() or not work.geometry.is_valid.all():raise ValueError('Le réseau contient des géométries invalides.')
    if not np.isfinite(max_snap_m) or max_snap_m<0:raise ValueError('La distance de rattachement doit être positive ou nulle.')
    coords=np.asarray([start,end],dtype=float)
    if coords.shape!=(2,2) or not np.isfinite(coords).all():raise ValueError('Départ et arrivée : deux coordonnées finies [x, y].')
    points=gpd.GeoSeries([Point(*coords[0]),Point(*coords[1])],crs=points_crs or original.crs).to_crs(work.crs)
    if not np.isfinite([(p.x,p.y) for p in points]).all():raise ValueError('La transformation des coordonnées produit des valeurs non finies ; vérifier points_crs et metric_crs.')
    _check_cancel(cancel)
    geometries=list(work.geometry.explode(index_parts=False))
    if node_intersections:
        merged=unary_union(geometries);geometries=list(merged.geoms) if hasattr(merged,'geoms') else [merged]
    _check_cancel(cancel)
    # Canonical segments remove duplicate/reversed edges without inventing
    # junctions where un-noded lines cross or an endpoint meets their interior.
    segments=set();number=0
    for line in geometries:
        pairs=list(line.coords)
        for a,b in zip(pairs,pairs[1:]):
            if number%1024==0:_check_cancel(cancel)
            number+=1
            a,b=tuple(map(float,a[:2])),tuple(map(float,b[:2]))
            if not np.isfinite((*a,*b)).all():raise ValueError('Le réseau contient des coordonnées non finies.')
            if a!=b:segments.add((a,b) if a<b else (b,a))
    if not segments:raise ValueError('Le réseau ne contient aucun segment de longueur positive.')
    nodes={};locations=[];adj=[]
    def node(xy):
        if xy not in nodes:nodes[xy]=len(locations);locations.append(xy);adj.append({})
        return nodes[xy]
    edges=[];lines=[]
    for number,(a,b) in enumerate(sorted(segments)):
        if number%1024==0:_check_cancel(cancel)
        line=LineString([a,b]);length=float(line.length)
        if not np.isfinite(length*factor) or length<=0:raise ValueError('Le réseau contient une longueur de segment invalide.')
        edges.append((node(a),node(b),length));lines.append(line)
    splits={}
    if snap=='node':
        tree=cKDTree(locations);dist,index=tree.query([[p.x,p.y] for p in points]);dist=np.asarray(dist)*factor
        if (dist>max_snap_m).any():raise ValueError('Aucun nœud du réseau dans la distance de rattachement demandée.')
    else:
        tree=STRtree(lines);dist=[];index=[]
        for point in points:
            _check_cancel(cancel)
            matches,distances=tree.query_nearest(point,return_distance=True,all_matches=True)
            choice=int(np.argmin(matches));edge=int(matches[choice]);attachment=float(distances[choice])*factor
            if attachment>max_snap_m:raise ValueError('Aucun segment du réseau dans la distance de rattachement demandée.')
            dist.append(attachment)
            u,v,length=edges[edge];offset=float(lines[edge].project(point))
            if offset<=0:index.append(u)
            elif offset>=length:index.append(v)
            else:
                projected=lines[edge].interpolate(offset);xy=(float(projected.x),float(projected.y))
                if xy==locations[u]:index.append(u);continue
                if xy==locations[v]:index.append(v);continue
                # Do not consult the global XY node map: a crossing on an
                # un-noded segment must remain topologically separate.
                interior=splits.setdefault(edge,{})
                if xy not in interior:
                    interior[xy]=(offset,len(locations));locations.append(xy);adj.append({})
                index.append(interior[xy][1])
    _check_cancel(cancel)
    for number,(u,v,length) in enumerate(edges):
        if number%1024==0:_check_cancel(cancel)
        cuts=sorted([(0.,u),*splits.get(number,{}).values(),(length,v)])
        for (left,a),(right,b) in zip(cuts,cuts[1:]):
            distance=(right-left)*factor
            if distance>0 and a!=b:
                adj[a][b]=min(adj[a].get(b,np.inf),distance);adj[b][a]=adj[a][b]
    first,last=map(int,index);cost={first:0.};previous={};heap=[(0.,first)];done=set()
    while heap:
        distance,u=heapq.heappop(heap)
        if u in done:continue
        done.add(u)
        if len(done)%1024==0:_check_cancel(cancel)
        if u==last:break
        for v,weight in adj[u].items():
            value=distance+weight
            if value<cost.get(v,np.inf):cost[v]=value;previous[v]=u;heapq.heappush(heap,(value,v))
    if last not in done:raise ValueError('Départ et arrivée appartiennent à des composantes déconnectées.')
    route=[last]
    while route[-1]!=first:
        if len(route)%1024==0:_check_cancel(cancel)
        route.append(previous[route[-1]])
    route.reverse();points_out=[locations[i] for i in route]
    coincident=first==last
    geometry=Point(points_out[0]) if coincident else LineString(points_out)
    result=gpd.GeoDataFrame(dict(distance_m=[cost[last]],start_snap_m=[dist[0]],end_snap_m=[dist[1]],
        nodes=[len(route)],snap_method=[snap],route_status=['coincident' if coincident else 'ok']),
        geometry=[geometry],crs=work.crs).to_crs(original.crs)
    _check_cancel(cancel)
    if progress:progress(1,1)
    _check_cancel(cancel)
    return result
