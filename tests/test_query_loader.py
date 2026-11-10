import pytest

from query_loader import QUERIES_DIR, load_query, quote_columns, read_query

TABLE = "my-project.tables.some_table"


def _all_query_names():
    return sorted(p.relative_to(QUERIES_DIR).with_suffix("").as_posix() for p in QUERIES_DIR.rglob("*.sql"))


def test_queries_folder_is_not_empty():
    assert _all_query_names()


@pytest.mark.parametrize("name", _all_query_names())
def test_every_query_renders_with_table_and_columns(name):
    sql = load_query(name, table=TABLE, columns=["a", "b"])
    assert "{" not in sql and "}" not in sql  # tidak ada placeholder tersisa
    assert f"`{TABLE}`" in sql
    assert "SELECT" in sql


def test_columns_are_backtick_quoted_in_order():
    sql = load_query("common/rainfall_cells", table=TABLE, columns=["rain_-6.5_106.6", "rain_-6.5_106.7"])
    assert "SELECT datetime, `rain_-6.5_106.6`, `rain_-6.5_106.7`" in sql


def test_optional_filters_are_query_parameters_not_string_concatenation():
    assert "@station" in read_query("prediction/prophet_weights")
    torch = read_query("prediction/torch_weights")
    assert "@station" in torch and "@horizon" in torch
    assert "@since" in read_query("common/rainfall_cells")


@pytest.mark.parametrize("bad_table", [
    "", "a b", "proj.ds.tbl`; DROP TABLE x; --", "a.b.c.d", "proj.ds.tbl\n", "`proj.ds.tbl`",
])
def test_invalid_table_rejected(bad_table):
    with pytest.raises(ValueError):
        load_query("common/select_all_ordered", table=bad_table)


@pytest.mark.parametrize("bad_columns", [[], [""], ["ok", "bad`col"], ["new\nline"], ["back\\slash"]])
def test_invalid_columns_rejected(bad_columns):
    with pytest.raises(ValueError):
        quote_columns(bad_columns)


def test_unknown_query_raises():
    with pytest.raises(FileNotFoundError):
        read_query("prediction/does_not_exist")
