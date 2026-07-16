from pathlib import Path
APP=(Path(__file__).resolve().parents[1]/'app'/'app.py').read_text()
assert 'CREATE TABLE IF NOT EXISTS vm_disk_io_history' in APP
assert 'CREATE TABLE IF NOT EXISTS node_storage_io_history' in APP
assert 'def _v5053_vm_snapshot_metric' in APP
assert 'node_sort_header("INTERFACE", "source"' in APP
assert "<th>{headers['drops']}</th><th>{headers['errors']}</th><th>{headers['source']}</th>" in APP
assert 'width:132px' in APP
assert '_v5052_copy_upsert_rows(conn, "vm_disk_io_history"' in APP
assert '_v5052_copy_upsert_rows(conn, "node_storage_io_history"' in APP
assert 'MOD(bucket,3600)<>0' in APP
print('PASS: v50.5.3 selected snapshot detail alignment')
