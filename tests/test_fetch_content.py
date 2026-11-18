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

