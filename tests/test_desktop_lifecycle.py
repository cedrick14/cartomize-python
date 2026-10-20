"""Repeated native worker lifecycle checks, including close while processing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import threading
import time

import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
import cartomize as cm
from cartomize.desktop import CartomizeWindow


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Qt lifecycle condition did not complete before deadline'


@pytest.mark.parametrize('method', ['cancel', 'close'])
def test_repeated_worker_lifecycle(application, method):
    for _ in range(3):
        started = threading.Event()
        window = CartomizeWindow()
        window.show()
        window.select_tool('workflow')
        timer = QTimer(window)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        ticks = []
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)

        def job(progress, event):
            started.set()
            while not event.wait(.01):
                pass
            raise cm.ProcessingCancelled()

        page = window.tool('workflow')
        page.staged = False
        page.job = lambda options: job
        try:
            window.start()
            wait_for(lambda: started.is_set() and len(ticks) >= 3)
            assert window.thread is not None
            if method == 'close':
                assert not window.close(), 'A running worker must postpone window destruction'
                assert isValid(window) and window.cancel_event.is_set()
            else:
                QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
            wait_for(lambda: window.thread is None)
            assert window.status.text() == 'Traitement interrompu.'
        finally:
            if isValid(timer):
                timer.stop()
            if isValid(window):
                if window.thread is not None:
                    window.cancel()
                    wait_for(lambda: window.thread is None, seconds=15)
                window.close()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                QTest.qWait(20)
        assert not isValid(window), 'Closed window should have released its native Qt object'
