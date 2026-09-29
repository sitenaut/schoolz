from services.backpack_parser import _extract_links, resource_content_hash

_PAGE_URL = "https://www.audubonschools.org/virtual-backpack"


def test_extracts_title_and_resolves_relative_wrapper_url():
    html = """
    <a href="/fs/resource-manager/view/8177c1b9-f8fc-4c92-8867-490c2be8e0b3">AHS</a>
    """
    links = _extract_links(html, _PAGE_URL)
    assert links == [
        {
            "resource_id": "8177c1b9-f8fc-4c92-8867-490c2be8e0b3",
            "title": "AHS",
            "wrapper_url": "https://www.audubonschools.org/fs/resource-manager/view/8177c1b9-f8fc-4c92-8867-490c2be8e0b3",
        }
    ]


def test_strips_nbsp_and_html_entities_from_title():
    # Confirmed real: "&nbsp;Picture Retakes" and "MAS Kershaw - Frozen the Musical&nbsp;"
    html = '<a href="/fs/resource-manager/view/61bed6af-4ff7-444a-ba54-3b707798b96b">&nbsp;Picture Retakes</a>'
    links = _extract_links(html, _PAGE_URL)
    assert links[0]["title"] == "Picture Retakes"


def test_dedupes_by_resource_id_keeping_first_occurrence():
    # Confirmed real: Audubon repeats "Saturday Storytime" and "Chess Club Flyer" under multiple sections.
    html = """
    <a href="/fs/resource-manager/view/aaaaaaaa-1111-1111-1111-111111111111">Chess Club Flyer</a>
    <a href="/fs/resource-manager/view/aaaaaaaa-1111-1111-1111-111111111111">Chess Club Flyer (again)</a>
    """
    links = _extract_links(html, _PAGE_URL)
    assert len(links) == 1
    assert links[0]["title"] == "Chess Club Flyer"


def test_absolute_wrapper_url_is_left_as_is():
    html = '<a href="https://www.audubonschools.org/fs/resource-manager/view/cd83d4d4-9416-4495-922c-5140dd8f153d">2NDFLOOR</a>'
    links = _extract_links(html, _PAGE_URL)
    assert links[0]["wrapper_url"] == "https://www.audubonschools.org/fs/resource-manager/view/cd83d4d4-9416-4495-922c-5140dd8f153d"


def test_link_with_no_text_is_skipped():
    html = '<a href="/fs/resource-manager/view/8177c1b9-f8fc-4c92-8867-490c2be8e0b3"><img src="icon.png"></a>'
    assert _extract_links(html, _PAGE_URL) == []


def test_unrelated_link_is_ignored():
    html = '<a href="/about-us">About Us</a>'
    assert _extract_links(html, _PAGE_URL) == []


def test_resource_content_hash_is_stable_and_id_specific():
    a = resource_content_hash("8177c1b9-f8fc-4c92-8867-490c2be8e0b3")
    b = resource_content_hash("8177c1b9-f8fc-4c92-8867-490c2be8e0b3")
    c = resource_content_hash("cd83d4d4-9416-4495-922c-5140dd8f153d")
    assert a == b
    assert a != c
