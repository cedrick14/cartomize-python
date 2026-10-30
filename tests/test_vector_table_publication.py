"""Exact CSV publication for the shared area/ring table writer."""
import json
from types import SimpleNamespace

import pandas as pd

from cartomize.processing import _write_verified_vector_tables
from cartomize.viewer_data import table_page


def test_nullable_floats_round_trip_without_losing_low_bits_or_labels(tmp_path):
    frame = pd.DataFrame({
        'area': pd.Series([0.20000000000000007, 4028192.2061842163, None], dtype='Float64'),
        'identifier': pd.Series([2**63 - 1, 2**53 + 1, None], dtype='Int64'),
        'code': pd.Series(['001', 'NA', ''], dtype='string'),
        'date_label': pd.Series(['2026-10-30', '', '2026-08-17'], dtype='string'),
        'present': pd.Series([True, False, None], dtype='boolean'),
    })
    result = SimpleNamespace(table=frame, summary={
        'area_unit': 'm2', 'measurement_crs': 'EPSG:32733'})
    products = _write_verified_vector_tables(result, tmp_path,
        vector_names=(), table_names=('table',),
        audit_schema='cartomize.table.audit.test.v1', error_label='Test table')

    # Read the exported numbers as decimal text and independently parse them
    # with Python, keeping verification independent of Pandas' dtype pathway.
    text = pd.read_csv(products['table'], dtype='string', keep_default_na=False)
    assert [float(value) for value in text['area'][:2]] == frame['area'][:2].tolist()
    assert text['area'][2] == ''
    assert [int(value) for value in text['identifier'][:2]] == [2**63 - 1, 2**53 + 1]
    assert text['identifier'][2] == ''
    assert text['code'].tolist() == ['001', 'NA', '']
    assert text['date_label'].tolist() == ['2026-10-30', '', '2026-08-17']
    assert text['present'].tolist() == ['True', 'False', '']
    audit = json.loads(products['audit'].read_text())
    assert audit['verified_files']['table.csv']['verification'] == 'exact_labels_and_numeric_values'
    # The GUI table reader must reproduce the same nullable numbers and codes,
    # including when it loads only a page containing a missing numeric value.
    pd.testing.assert_frame_equal(table_page(products['table'])['frame'], frame,
                                  check_exact=True)
    page = table_page(products['table'], offset=1, size=2)
    pd.testing.assert_frame_equal(page['frame'], frame.iloc[1:].reset_index(drop=True),
                                  check_exact=True)
