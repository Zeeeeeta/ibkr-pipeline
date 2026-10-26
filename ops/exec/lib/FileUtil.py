#!/usr/bin/env python3
"""Local substitute for /q/common/exec/lib/FileUtil."""


def populateDateValues(file_name, pdate):
    """
    Expand date tokens in a file path template.

    Supported placeholders (longest match first): YYYYMMDD, YYYY, MMDD, MM, DD.
    *pdate* is typically an eight-digit string YYYYMMDD.
    """
    d = str(pdate).strip()
    if len(d) == 8 and d.isdigit():
        y, m, dd = d[:4], d[4:6], d[6:8]
        out = file_name
        for token, value in (
            ('YYYYMMDD', d),
            ('YYYY', y),
            ('MMDD', m + dd),
            ('MM', m),
            ('DD', dd),
        ):
            out = out.replace(token, value)
        return out
    return file_name.replace('YYYYMMDD', d)
