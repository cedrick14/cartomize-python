"""Import local teaching data without adding it to the public repository."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from course import import_tuto

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('archive',type=Path)
parser.add_argument('--destination',type=Path,default=Path(__file__).resolve().parents[1]/'data/private')
args=parser.parse_args()
result=import_tuto(args.archive,args.destination)
print(f'{len(result["datasets"])} jeux de données importés dans {args.destination}')
