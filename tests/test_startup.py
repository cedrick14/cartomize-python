"""Cold imports and a real Jupyter kernel must work without user setup code."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


def test_installed_startup_in_fresh_process():
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_startup.py'
    result = subprocess.run([sys.executable, str(script), '--gui'],
                            capture_output=True, text=True, timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CARTOMIZE_STARTUP_OK' in result.stdout
    assert 'CARTOMIZE_GUI_OK' in result.stdout


def test_notebook_launch_returns_and_processes_qt_events(tmp_path):
    client = pytest.importorskip('jupyter_client')
    pytest.importorskip('ipykernel')
    pytest.importorskip('PySide6')
    manager = client.KernelManager(kernel_name='python3')
    manager.kernel_spec.argv[0] = sys.executable
    manager.start_kernel(cwd=str(tmp_path), env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
    connection = manager.client()
    connection.start_channels()
    try:
        connection.wait_for_ready(timeout=45)
        msg_id = connection.execute(
            "import cartomize as cm\n"
            "window = cm.launch()\n"
            "assert window.isVisible()\n"
            "from PySide6.QtCore import QTimer\n"
            "QTimer.singleShot(100, lambda: print('CARTOMIZE_QT_EVENT', flush=True))\n"
            "print('CARTOMIZE_CELL_RETURNED', flush=True)\n"
        )
        deadline = time.monotonic() + 45
        while True:
            reply = connection.get_shell_msg(timeout=max(.1, deadline - time.monotonic()))
            if reply['parent_header'].get('msg_id') == msg_id:
                assert reply['content']['status'] == 'ok', reply['content']
                break
        output = ''
        deadline = time.monotonic() + 20
        while 'CARTOMIZE_QT_EVENT' not in output:
            message = connection.get_iopub_msg(timeout=max(.1, deadline - time.monotonic()))
            if message['msg_type'] == 'error':
                pytest.fail(str(message['content']))
            output += message['content'].get('text', '')
        assert 'CARTOMIZE_CELL_RETURNED' in output
        connection.execute('window.close()')
    finally:
        connection.stop_channels()
        manager.shutdown_kernel(now=True)
