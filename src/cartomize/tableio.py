"""Delimited-table input with explicit delimiter detection and float fidelity."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd


def read_table(path: str | Path, *, nrows: int | None = None,
               dtype: Any = None, delimiter: str | None = None,
               encoding: str = 'utf-8-sig') -> pd.DataFrame:
    """Read a local CSV/TSV without changing round-trip floating-point values.

    Sniffing is bounded to 64 KiB; parsing uses the C round-trip converter.
    Accepted automatic separators are comma, semicolon, tab and vertical bar.
    ``dtype`` may explicitly preserve identifiers such as leading-zero codes.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    options: dict[str, Any] = {}
    if delimiter is None:
        with source.open('r', encoding=encoding, newline='') as handle:
            sample = handle.read(65536)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            delimiter = dialect.delimiter
            options['quotechar'] = dialect.quotechar or '"'
            options['skipinitialspace'] = dialect.skipinitialspace
        except csv.Error:
            # A one-column table has no separator. Do not infer a letter or
            # digit as the delimiter, as unrestricted sniffing can do.
            first = next((line for line in sample.splitlines() if line.strip()), '')
            if any(separator in first for separator in ',;\t|'):
                raise ValueError('Séparateur du tableau indéterminé. Indiquer un délimiteur explicite.') from None
            delimiter = '\t' if source.suffix.lower() == '.tsv' else ','
    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise ValueError('Le délimiteur doit contenir un seul caractère.')
    return pd.read_csv(source, sep=delimiter, engine='c', float_precision='round_trip',
                       encoding=encoding, nrows=nrows, dtype=dtype,
                       low_memory=False, **options)
