"""Build a browsable, offline HTML edition from the saved notebooks."""
from pathlib import Path
import html,json,shutil
import nbformat
from nbconvert import HTMLExporter
ROOT=Path(__file__).resolve().parents[1]
site=ROOT/'site';site.mkdir(exist_ok=True)
exporter=HTMLExporter(template_name='lab')
records=json.loads((ROOT/'catalog.json').read_text())
images={'00':'00_premiere','01':'01_proximite','02':'02_composite','03':'03_ndvi',
'04':'04_classification','05':'05_changements','06':'06_terrain','07':'07_planche',
'11':'11_mvouti','12':'12_okapis'}
cards=[]
for item in records:
 path=ROOT/'notebooks'/(item['slug']+'.ipynb')
 notebook=nbformat.read(path,as_version=4)
 body,_=exporter.from_notebook_node(notebook)
 # Exported Markdown retains the notebook's relative references.
 body=body.replace('../gallery/','gallery/').replace('../README.md','../README.md')
 (site/(item['slug']+'.html')).write_text(body,encoding='utf-8')
 key=item['slug'][:2];image=images.get(key)
 image=image if image and (ROOT/'gallery'/(image+'.png')).exists() else None
 visual=f'<img src="gallery/{image}.png" alt="Aperçu du résultat" loading="lazy">' if image else f'<div class="number">{key}</div>'
 label='Données locales' if item['real'] else 'Données pédagogiques'
 cards.append(f'<a class="card" href="{item["slug"]}.html">{visual}<div class="body"><span>{label} · {item["minutes"]} min</span><h2>{html.escape(item["title"])}</h2><p>Explications, code, résultats et exercice corrigé</p></div></a>')
if (ROOT/'gallery').exists():shutil.copytree(ROOT/'gallery',site/'gallery',dirs_exist_ok=True)
css='''body{margin:0;font:17px/1.55 system-ui,sans-serif;color:#20272b;background:#f4f5f3}main{max-width:1180px;margin:auto;padding:48px 24px}header{max-width:900px;margin-bottom:36px}h1{font-size:clamp(32px,5vw,52px);line-height:1.13;letter-spacing:-1px;margin:12px 0}h2{font-size:20px;line-height:1.3;margin:12px 0}p{margin:10px 0}.tag{font-size:14px;font-weight:650;letter-spacing:1px;text-transform:uppercase}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}.card{display:block;color:inherit;text-decoration:none;background:white;border:1px solid #d9ddda;border-radius:12px;overflow:hidden;transition:box-shadow .2s}.card:hover{box-shadow:0 6px 24px #253c3820}.card img{width:100%;height:235px;object-fit:contain;background:#fff;border-bottom:1px solid #e9ece8}.body{padding:22px}.body span{font-size:13px;color:#54645b}.body p{font-size:14px;color:#5e686b}.number{height:235px;display:grid;place-items:center;font-size:76px;color:#426c5b;background:#edf2ed}.note{padding:20px;background:white;border-left:3px solid #547865;margin:24px 0}footer{margin-top:36px;color:#59635d;font-size:14px}a:focus{outline:3px solid #316b53}'''
page=f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cartomize | Projets pratiques</title><style>{css}</style></head><body><main><header><div class="tag">Cartomize · Version 1.0</div><h1>Des données géographiques aux cartes reproductibles</h1><p>Treize projets pour préparer, analyser, représenter et automatiser. Chaque cours associe le raisonnement, les paramètres, le code et les résultats.</p></header><div class="note">Cette édition HTML permet la lecture hors ligne. Pour exécuter le code et les contrôles interactifs, ouvrir les notebooks dans Jupyter. Les cas réels demandent les fichiers de Tuto.zip.</div><section class="grid">{''.join(cards)}</section><footer>ONDON NKOUA Cédrick Belmich / Cartomize. Les données simulées sont pédagogiques. Les cartes réelles conservent les limites de leurs sources.</footer></main></body></html>'''
(site/'index.html').write_text(page,encoding='utf-8')
print(f'{len(records)} cours exportés ; ouvrir {site/"index.html"}')
