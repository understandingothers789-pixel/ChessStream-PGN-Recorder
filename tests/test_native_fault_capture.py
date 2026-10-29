"""Exercise native fault diagnostics in an isolated child, never the test runner."""
import os
import subprocess
import sys
import zipfile
from chessstream.storage import Store
from chessstream.diagnostics import export_diagnostics


def test_child_fault_stack_is_written_and_exported(tmp_path):
    # dump_traceback exercises the same descriptor without crashing the host.
    result=subprocess.run([sys.executable,'-c',
        'import faulthandler,sys; from pathlib import Path; '
        'from chessstream.diagnostics import configure_logging; '
        'configure_logging(Path(sys.argv[1])); '
        'import chessstream.diagnostics as d; '
        'faulthandler.dump_traceback(file=d._native_fault_file,all_threads=True)',str(tmp_path)],
        capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr
    contents=(tmp_path/'native-crash.log').read_text()
    assert 'Launch ' in contents and 'most recent call first' in contents
    store=Store(tmp_path);path=export_diagnostics(store,tmp_path/'support.zip')
    with zipfile.ZipFile(path) as archive:
        assert 'most recent call first' in archive.read('logs/native-crash.log').decode()
    store.close()
