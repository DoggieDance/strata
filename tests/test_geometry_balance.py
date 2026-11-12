"""Consolidated city-counties: the ACS publishes the "(balance)" place; boundary
files may add the whole consolidated area under a sibling code (Kentucky 2020:
2148000 beside 2148006). Found by the national build."""
import geopandas as gpd
from shapely.geometry import box

from etl.build_geometry import balance_polygons

NAMES = {"2148006": "Louisville/Jefferson County metro government (balance), Kentucky",
         "2140000": "Jeffersontown city, Kentucky"}


def frame(rows):
    return gpd.GeoDataFrame([{"GEOID": g, "geometry": geom} for g, geom in rows], crs=4326)


def test_overlapping_whole_area_is_dropped_when_balance_has_a_polygon():
    g = frame([("2148000", box(0, 0, 10, 10)), ("2148006", box(0, 0, 10, 8)), ("2140000", box(0, 8, 10, 10))])
    out = balance_polygons(g, {"2148006", "2140000"}, NAMES)
    assert sorted(out.GEOID) == ["2140000", "2148006"]
    assert out.set_index("GEOID").geometry["2148006"].area == 80


def test_balance_drawn_as_whole_minus_places_when_missing():
    g = frame([("2148000", box(0, 0, 10, 10)), ("2140000", box(0, 8, 10, 10))])
    out = balance_polygons(g, {"2148006", "2140000"}, NAMES)
    assert sorted(out.GEOID) == ["2140000", "2148006"]
    assert abs(out.set_index("GEOID").geometry["2148006"].area - 80) < 1e-9


def test_ordinary_places_untouched():
    g = frame([("2140000", box(0, 0, 1, 1))])
    assert balance_polygons(g, {"2140000"}, NAMES).equals(g)
