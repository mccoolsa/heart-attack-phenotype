"""Run the same SQL on DuckDB (local) or Spark SQL (Databricks).

The checks and the phenotype only need `con.execute(sql)` with `fetchall()`,
`fetchone()` and `df()`. A DuckDB connection already has that interface;
`SparkConnection` gives a SparkSession the same one. The few functions whose
names differ between the two engines go through the helpers below.
"""
from __future__ import annotations

import pandas as pd


class SparkConnection:
    """DuckDB-style facade over a SparkSession."""

    dialect = "spark"

    def __init__(self, spark, schema: str | None = None):
        self.spark = spark
        if schema:
            spark.sql(f"use {schema}")
        self._df = None

    def execute(self, sql: str, params=None):
        if params:
            raise NotImplementedError("use literals; Spark SQL has no positional parameters here")
        self._df = self.spark.sql(sql)
        return self

    def fetchall(self):
        return [tuple(r) for r in self._df.collect()]

    def fetchone(self):
        rows = self._df.limit(1).collect()
        return tuple(rows[0]) if rows else None

    def df(self) -> pd.DataFrame:
        return self._df.toPandas()


def is_spark(con) -> bool:
    return getattr(con, "dialect", "duckdb") == "spark"


def regex(con, expr: str, pattern: str) -> str:
    """Boolean SQL: does `expr` match the regular expression `pattern`?"""
    if is_spark(con):
        # Spark SQL string literals treat backslash as an escape character
        return f"({expr} rlike '{pattern.replace(chr(92), chr(92) * 2)}')"
    return f"regexp_matches({expr}, '{pattern}')"


def epoch_seconds(con, expr: str) -> str:
    return f"unix_timestamp({expr})" if is_spark(con) else f"epoch({expr})"


def concat_distinct(con, expr: str) -> str:
    """Aggregate: distinct values joined with ';'."""
    if is_spark(con):
        return f"array_join(array_sort(collect_set({expr})), ';')"
    return f"string_agg(distinct {expr}, ';' order by {expr})"


def create_table_from_pandas(con, name: str, df: pd.DataFrame) -> None:
    if is_spark(con):
        con.spark.createDataFrame(df).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    else:
        con.register("_tmp_df", df)
        con.execute(f"create or replace table {name} as select * from _tmp_df")
        con.unregister("_tmp_df")
