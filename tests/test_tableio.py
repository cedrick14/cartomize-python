"""Regression tests for full-precision coordinate input in desktop tools."""
import numpy as np
import pandas as pd
import pytest
from cartomize.tableio import read_table


@pytest.mark.parametrize('separator', [',', ';', '\t', '|'])
def test_coordinate_round_trip_preserves_floats(tmp_path, separator):
    values = [6866673.2885795515, 6860114.327655802, -0.12345678912345678,
              float(np.nextafter(1.0, 2.0))]
    frame = pd.DataFrame({'id': [1, 2, 3, 4], 'x': values, 'y': values[::-1]})
    path = tmp_path / ('points.tsv' if separator == '\t' else 'points.csv')
    frame.to_csv(path, sep=separator, index=False)
    pd.testing.assert_frame_equal(read_table(path), frame, check_exact=True)


def test_quoted_text_and_utf8_bom(tmp_path):
    path = tmp_path / 'quoted.csv'
    frame = pd.DataFrame({'name': ['Quartier, école', 'Parc; nord'], 'value': [1.25, 2.75]})
    frame.to_csv(path, sep=';', index=False, encoding='utf-8-sig')
    pd.testing.assert_frame_equal(read_table(path), frame)
    assert list(read_table(path, nrows=0)) == ['name', 'value']


def test_explicit_identifier_type_preserves_leading_zero(tmp_path):
    path = tmp_path / 'codes.csv'
    path.write_text('code\n001\n002\n', encoding='utf-8')
    assert read_table(path, dtype={'code': 'string'})['code'].tolist() == ['001', '002']


def test_explicit_delimiter_and_missing_file(tmp_path):
    path = tmp_path / 'table.csv'
    path.write_text('x;y\n1;2\n', encoding='utf-8')
    assert read_table(path, delimiter=';').iloc[0].tolist() == [1, 2]
    with pytest.raises(ValueError):
        read_table(path, delimiter=';;')
    with pytest.raises(FileNotFoundError):
        read_table(tmp_path / 'absent.csv')
