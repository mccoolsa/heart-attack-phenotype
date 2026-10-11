"""Salted one-way hashing of patient identifiers, as NHS Secure Data Environments do.

MIMIC is already de-identified; this step demonstrates the pattern so published
outputs never carry the source subject_id. The salt comes from the HAPDQ_SALT
environment variable; the default is for local runs only.
"""
from __future__ import annotations

import hashlib
import os
import warnings

import pandas as pd

DEFAULT_SALT = "local-dev-salt-change-me"


def get_salt() -> str:
    salt = os.environ.get("HAPDQ_SALT")
    if not salt:
        warnings.warn("HAPDQ_SALT not set - using the public default salt; ids are reversible by brute force.")
        return DEFAULT_SALT
    return salt


def pseudo_id(subject_id: int | str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{subject_id}".encode()).hexdigest()[:16]


def pseudonymise(df: pd.DataFrame, salt: str, cols: tuple[str, ...] = ("subject_id",),
                 drop: tuple[str, ...] = ("hadm_id",)) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out:
            out.insert(0, "pseudo_id", out.pop(c).map(lambda x: pseudo_id(x, salt)))
    return out.drop(columns=[c for c in drop if c in out])
