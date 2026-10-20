"""Idempotent, guarded source migration for the desktop workbench.

Executed on the development branch before validation, never on user startup.
Every edited Python file is parsed before it is written and committed.
"""
from pathlib import Path
import ast
import hashlib

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '030b328001098ccb418f034394fbe5bad0d16d9b'


def write_python(path, source):
    ast.parse(source, filename=str(path))
    path.write_text(source, encoding='utf-8', newline='\n')


def replace_once(path, before, after):
    path = ROOT / path
    source = path.read_text(encoding='utf-8')
    if after in source:
        return
    if source.count(before) != 1:
        raise SystemExit(f'Expected one integration anchor in {path.name}')
    write_python(path, source.replace(before, after, 1))


def main():
    path = ROOT / 'src/cartomize/desktop.py'
    raw = path.read_bytes()
    source = raw.decode('utf-8')
    if '        install_workbench(self)' not in source:
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
        write_python(path, source)

    # A map must retain an actual viewport when two documents share the space.
    # Qt splitters otherwise permit a child to collapse to a zero-width canvas.
    replace_once('src/cartomize/desktop_results.py',
                 'self.content=QSplitter(Qt.Orientation.Horizontal); layout.addWidget(self.content,1)',
                 'self.content=QSplitter(Qt.Orientation.Horizontal); self.content.setChildrenCollapsible(False); layout.addWidget(self.content,1)')
    replace_once('src/cartomize/desktop_results.py',
                 "self.views=QTabWidget(); self.views.addTab(self.canvas,'Carte' if self.canvas.info.get('crs') else 'Document'); self.content.addWidget(self.views)",
                 "self.canvas.setMinimumSize(160,120)\n        self.views=QTabWidget(); self.views.setMinimumSize(180,150); self.views.addTab(self.canvas,'Carte' if self.canvas.info.get('crs') else 'Document'); self.content.addWidget(self.views)")
    replace_once('src/cartomize/desktop_results.py',
                 'self.splitter=QSplitter(Qt.Orientation.Horizontal); layout.addWidget(self.splitter,1); self.choices=[]; self.holders=[]',
                 'self.splitter=QSplitter(Qt.Orientation.Horizontal); self.splitter.setChildrenCollapsible(False); layout.addWidget(self.splitter,1); self.choices=[]; self.holders=[]')
    # QSettings INI values are strings after reload; use the same conversion as
    # the application rather than asserting a platform-specific storage type.
    replace_once('tests/test_desktop_workbench.py',
                 "assert window._preferences.value('appearance/font_size') == 14",
                 "assert int(window._preferences.value('appearance/font_size')) == 14")
    # Sessions written before the workbench stored controls before the map.
    replace_once('src/cartomize/desktop_session.py',
                 'workspace=self.workspace.capture(),splitter=self.workspace_splitter.sizes(),processing=',
                 "workspace=self.workspace.capture(),splitter=self.workspace_splitter.sizes(),workspace_order=('map-controls' if self.workspace_splitter.indexOf(self.workspace)==0 else 'controls-map'),processing=")
    replace_once('src/cartomize/desktop_session.py',
                 "            if state.get('splitter'):self.workspace_splitter.setSizes(state['splitter'])",
                 "            if state.get('splitter'):\n                sizes=list(state['splitter'])\n                current_order='map-controls' if self.workspace_splitter.indexOf(self.workspace)==0 else 'controls-map'\n                if state.get('workspace_order','controls-map')!=current_order:sizes.reverse()\n                self.workspace_splitter.setSizes(sizes)")
    print('Desktop integration, non-collapsible maps and session compatibility applied')


if __name__ == '__main__':
    main()
