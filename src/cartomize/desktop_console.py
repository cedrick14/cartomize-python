"""Desktop console and environment panels; no optional Qt add-ons required."""
from __future__ import annotations

from importlib import metadata
import json
from pathlib import Path
import platform
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


class ConsolePanel(QWidget):
    activity = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._buffer = b''
        self._pending = None
        self._sequence = 0
        self._ready = False
        self.busy = False
        self.context_paths = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(3000)
        self.output.setObjectName('consoleOutput')
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.output, 2)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName('consoleEditor')
        self.editor.setPlaceholderText('Code Python')
        self.editor.setFont(self.output.font())
        self.editor.setMinimumHeight(54)
        self.editor.setMaximumHeight(125)
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.execute_button = QPushButton('Exécuter le code')
        self.execute_button.setObjectName('primary')
        self.execute_button.clicked.connect(self.execute)
        self.stop_button = QPushButton('Interrompre')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.interrupt)
        clear = QPushButton('Effacer la sortie')
        clear.clicked.connect(self.output.clear)
        self.state = QLabel('Noyau arrêté')
        row.addWidget(self.execute_button)
        row.addWidget(self.stop_button)
        row.addWidget(clear)
        row.addStretch()
        row.addWidget(self.state)
        layout.addLayout(row)
        self.run_shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.editor)
        self.run_shortcut.activated.connect(self.execute)

    def _write(self, message):
        payload = json.dumps(message, ensure_ascii=True).encode('utf-8') + b'\n'
        self.process.write(payload)

    def execute(self):
        source = self.editor.toPlainText().strip()
        if not source or self.busy:
            return
        self._sequence += 1
        self._pending = {'op': 'execute', 'id': self._sequence, 'code': source}
        self.busy = True
        self.execute_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.output.appendPlainText('>>> ' + source)
        self.state.setText('Exécution')
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._ready = False
            self._buffer = b''
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert('PYTHONIOENCODING', 'utf-8')
            environment.insert('MPLBACKEND', 'Agg')
            self.process.setProcessEnvironment(environment)
            self.process.setProgram(sys.executable)
            self.process.setArguments(['-u', '-m', 'cartomize.desktop_kernel'])
            self.process.start()
        elif self._ready:
            self._submit()

    def _submit(self):
        if self._pending is not None:
            self._write({'op': 'context', 'paths': list(self.context_paths)})
            self._write(self._pending)
            self._pending = None

    def _read_stdout(self):
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            if not line:
                continue
            try:
                record = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeError):
                self.output.appendPlainText(line.decode('utf-8', errors='replace'))
                continue
            kind = record.get('type')
            if kind == 'ready':
                self._ready = True
                self.activity.emit('Console Python initialisée')
                self._submit()
            elif kind in {'stdout', 'stderr', 'result', 'error'}:
                text = record.get('text', '')
                if text.strip():
                    self.output.appendPlainText(text.rstrip('\n'))
            elif kind == 'finished':
                self.busy = False
                self.execute_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.state.setText('Prêt' if record.get('ok') else 'Erreur Python')
                self.activity.emit('Console : exécution terminée' if record.get('ok') else 'Console : erreur Python')

    def _read_stderr(self):
        text = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace')
        if text.strip():
            self.output.appendPlainText(text.rstrip('\n'))

    def _finished(self, code, status):
        self._read_stdout()
        self._ready = False
        self._pending = None
        self.busy = False
        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.state.setText('Noyau arrêté')
        if status == QProcess.ExitStatus.CrashExit:
            self.activity.emit('Console : processus interrompu')

    def _process_error(self, error):
        self.output.appendPlainText(self.process.errorString())
        if error == QProcess.ProcessError.FailedToStart:
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def interrupt(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        self._pending = None

    def shutdown(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        if not self.busy and self._ready:
            self._write({'op': 'shutdown'})
        else:
            self.process.terminate()
        if not self.process.waitForFinished(1000):
            self.process.kill()
            self.process.waitForFinished(1000)


class EnvironmentPanel(QWidget):
    PACKAGES = ('cartomize', 'PySide6-Essentials', 'rasterio', 'geopandas',
                'numpy', 'pandas', 'scipy', 'scikit-learn', 'shapely',
                'pyproj', 'matplotlib', 'pypdfium2')

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Paquet', 'Version'])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        refresh = QPushButton('Actualiser')
        refresh.clicked.connect(self.refresh)
        copy = QPushButton('Copier le diagnostic')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.diagnostic_text()))
        export = QPushButton('Enregistrer le diagnostic')
        export.clicked.connect(self.export)
        row.addWidget(refresh)
        row.addWidget(copy)
        row.addWidget(export)
        row.addStretch()
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.records = {}
        self.table.clear()
        for package in self.PACKAGES:
            try:
                version = metadata.version(package)
            except metadata.PackageNotFoundError:
                version = 'Non installé'
            self.records[package] = version
            self.table.addTopLevelItem(QTreeWidgetItem([package, version]))
        self.table.resizeColumnToContents(0)
        self.summary.setText(f'Python {platform.python_version()}\n{sys.executable}')

    def diagnostic_text(self):
        return json.dumps({'python': platform.python_version(), 'executable': sys.executable,
                           'system': platform.platform(), 'packages': self.records},
                          ensure_ascii=False, indent=2)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Diagnostic de l’environnement',
                                            'cartomize-environnement.json', 'JSON (*.json)')
        if path:
            try:
                Path(path).write_text(self.diagnostic_text(), encoding='utf-8')
            except OSError as exc:
                QMessageBox.warning(self, 'Enregistrement impossible', str(exc))
