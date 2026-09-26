"""Execute and export the course notebooks with an isolated kernel per lesson."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,re,sys,time
import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter
from jupyter_client import KernelManager
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--include-tuto',action='store_true')
p.add_argument('--select',nargs='*')
p.add_argument('--timeout',type=int,default=600)
p.add_argument('--transport',choices=['tcp','ipc'],default='tcp')
args=p.parse_args()
os.environ.setdefault('MPLBACKEND','Agg')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
report=[]; site=ROOT/'site';site.mkdir(exist_ok=True)
for path in sorted((ROOT/'notebooks').glob('*.ipynb')):
 if args.select and not any(path.stem.startswith(s) for s in args.select):continue
 notebook=nbformat.read(path,as_version=4)
 if notebook.metadata.cartomize_course.requires_tuto and not args.include_tuto:
  report.append({'notebook':path.name,'status':'requires_local_data'});continue
 started=time.perf_counter();print('START',path.name,flush=True)
 try:
  manager=KernelManager(kernel_name='python3',transport=args.transport)
  try:
   NotebookClient(notebook,km=manager,timeout=args.timeout,resources={'metadata':{'path':str(ROOT)}},record_timing=True).execute()
  finally:
   if manager.has_kernel:manager.shutdown_kernel(now=True)
  for cell in notebook.cells:
   if cell.cell_type=='code':
    for output in cell.get('outputs',[]):
     if 'text' in output:output.text=output.text.replace(str(ROOT),'tutorials')
     for key in ('text/plain','text/html'):
      if key in output.get('data',{}):output.data[key]=output.data[key].replace(str(ROOT),'tutorials')
  nbformat.write(notebook,path)
  html,_=HTMLExporter(template_name='lab').from_notebook_node(notebook)
  (site/(path.stem+'.html')).write_text(html,encoding='utf-8')
  status={'notebook':path.name,'status':'passed','code_cells':sum(c.cell_type=='code' for c in notebook.cells),'seconds':round(time.perf_counter()-started,2)}
  print('PASS',path.name,status['seconds'],flush=True)
 except Exception as exc:
  status={'notebook':path.name,'status':'failed','error':str(exc),'seconds':round(time.perf_counter()-started,2)}
  print('FAIL',path.name,str(exc)[-2500:],flush=True)
 report.append(status)
 (site/'execution.json').write_text(json.dumps({'date':datetime.now(timezone.utc).isoformat(),'results':report},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{k:v for k,v in r.items() if k!='error'} for r in report],indent=2),flush=True)
if any(r['status']=='failed' for r in report):sys.exit(1)
