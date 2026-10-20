"""Apply the desktop integration once, preserving all processing implementations.

This migration checks the exact baseline blob and syntax before replacing files.
It is run on the development branch, not when users import or install Cartomize.
"""
from pathlib import Path
import ast
import hashlib

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'src/cartomize/desktop.py'
BASELINE = '030b328001098ccb418f034394fbe5bad0d16d9b'


def main():
    raw = TARGET.read_bytes()
    source = raw.decode('utf-8')
    if '        install_workbench(self)' in source:
        ast.parse(source)
        print('Desktop integration already present')
        return
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != BASELINE:
        raise SystemExit(f'Desktop baseline changed ({blob}); reconcile before applying')
    start = source.index('    def apply_theme(self,*_):')
    end = source.index('    def page_changed(self,index):', start)
    source = source[:start] + '''    def apply_theme(self,*_):
        from .desktop_theme import apply_theme
        apply_theme(self)

    def filter_tools(self,text):
        if hasattr(self, '_workbench'):
            self._workbench.filter_tools(text)
            return
        for i in range(self.navigation.count()):
            self.navigation.item(i).setHidden(text.casefold() not in self.navigation.item(i).text().casefold())

''' + source[end:]
    needle = '        self.theme_selector.currentIndexChanged.connect(self.apply_theme)\n        self.apply_theme()\n'
    if source.count(needle) != 1:
        raise SystemExit('Ambiguous desktop initialization point')
    source = source.replace(needle, needle + '        from .desktop_workbench import install_workbench\n        install_workbench(self)\n', 1)
    ast.parse(source)
    TARGET.write_text(source, encoding='utf-8', newline='\n')
    print('Connected desktop workbench and appearance controller')


if __name__ == '__main__':
    main()
