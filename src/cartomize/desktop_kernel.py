"""Line-delimited JSON protocol for the optional desktop Python console.

Only code explicitly submitted by the local user is executed. Project files
are never evaluated. The process can be terminated independently of Qt tools.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
from pathlib import Path
import sys
import traceback


def serve(input_stream=None, output_stream=None):
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout

    def emit(kind, **fields):
        output_stream.write(json.dumps({'type': kind, **fields}, ensure_ascii=True) + '\n')
        output_stream.flush()

    class Stream(io.TextIOBase):
        def __init__(self, kind):
            self.kind = kind

        def writable(self):
            return True

        @property
        def encoding(self):
            return 'utf-8'

        def write(self, text):
            if text:
                emit(self.kind, text=str(text))
            return len(text)

        def flush(self):
            output_stream.flush()

    namespace = {'__name__': '__cartomize_console__', 'Path': Path}
    stdout, stderr = Stream('stdout'), Stream('stderr')
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            import cartomize as cm
            namespace['cm'] = cm
        emit('ready', python=sys.version.split()[0], cartomize=cm.__version__)
    except Exception:
        emit('error', text=traceback.format_exc())
        return 1

    for raw in input_stream:
        request_id = None
        try:
            message = json.loads(raw)
            request_id = message.get('id')
            operation = message.get('op', 'execute')
            if operation == 'shutdown':
                break
            if operation == 'context':
                paths = message.get('paths', [])
                if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                    raise ValueError('Invalid path context')
                namespace['data_paths'] = tuple(paths)
                emit('context', count=len(paths))
                continue
            if operation != 'execute':
                raise ValueError('Unsupported console operation')
            source = message.get('code', '')
            if not isinstance(source, str):
                raise ValueError('Console code must be text')
            if len(source) > 1_000_000:
                raise ValueError('Console submission exceeds one million characters')
            emit('started', id=request_id)
            tree = ast.parse(source, filename='<Cartomize console>', mode='exec')
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    expression = ast.Expression(tree.body.pop().value)
                    exec(compile(tree, '<Cartomize console>', 'exec'), namespace)
                    value = eval(compile(expression, '<Cartomize console>', 'eval'), namespace)
                    if value is not None:
                        namespace['_'] = value
                        representation = repr(value)
                        emit('result', id=request_id, text=representation[:20000])
                else:
                    exec(compile(tree, '<Cartomize console>', 'exec'), namespace)
            emit('finished', id=request_id, ok=True)
        except BaseException:
            # SystemExit and KeyboardInterrupt must not take down the desktop.
            emit('error', id=request_id, text=traceback.format_exc())
            emit('finished', id=request_id, ok=False)
    return 0


def main():
    return serve()


if __name__ == '__main__':
    raise SystemExit(main())
