"""The downloader refuses a firewall page saved under a data file's name (etl/fetch_summary_file.check_content)."""
import pytest

from etl.fetch_summary_file import NotTheFile, check_content

REJECTED = b"<html><head><title>Request Rejected</title></head><body>The requested URL was rejected."


@pytest.mark.parametrize("name", ["20195ma0015000.zip", "e20195ma0015000.txt", "ACS20155YR.dat", "lookup.csv"])
def test_rejection_page_is_refused(name):
    with pytest.raises(NotTheFile):
        check_content(name, REJECTED)


def test_html_content_type_is_refused():
    with pytest.raises(NotTheFile):
        check_content("x.dat", b"GEO_ID|B01001_E001", "text/html; charset=utf-8")


def test_real_files_pass():
    check_content("a.zip", b"PK\x03\x04\x14\x00")
    check_content("a.dat", b"GEO_ID|B01001_E001", "application/octet-stream")
    check_content("page.html", REJECTED)


def test_zip_without_signature_is_refused():
    with pytest.raises(NotTheFile, match="not a zip"):
        check_content("a.zip", b"\x00\x00\x00\x00")



def test_bundle_for_maps_a_sequence_file_to_its_state_bundle():
    from etl.fetch_summary_file import bundle_for
    base = "https://www2.census.gov/programs-surveys/acs/summary_file"
    assert bundle_for("2015-2019", "25", f"{base}/2019/data/5_year_seq_by_state/Massachusetts/Tracts_Block_Groups_Only/20195ma0015000.zip") \
        == f"{base}/2019/data/5_year_by_state/Massachusetts_Tracts_Block_Groups_Only.zip"
    assert bundle_for("2011-2015", "21", f"{base}/2015/data/5_year_seq_by_state/Kentucky/All_Geographies_Not_Tracts_Block_Groups/20155ky0003000.zip") \
        == f"{base}/2015/data/5_year_by_state/Kentucky_All_Geographies_Not_Tracts_Block_Groups.zip"
    assert bundle_for("2016-2020", "25", "anything") is None  # table-based periods have no bundles


def test_files_taken_from_bundles_say_so():
    """Every raw file that came from a state bundle records the bundle, its hash,
    and how many directly sent files the bundle was checked against."""
    import json
    from tests.conftest import ROOT
    metas = [json.loads(p.read_text()) for p in (ROOT / "data/raw/acs").rglob("*.zip.meta.json")]
    for m in (m for m in metas if m.get("source") == "bundle"):
        assert m["bundle_url"] and m["bundle_sha256"] and m["checked_against_direct_downloads"] > 0, m
