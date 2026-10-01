from services.school_info import _parse_edlio_footer


def test_edlio_enf_address_footer_reads_address_and_plain_text_phone():
    html = (
        '<div class="enf-address"><a href="/apps/maps" target="_blank">'
        "123 Parkview Road <br/>\n    Stratford, NJ 08084\n</a>"
        '<a href="/apps/contact">P:  (856) 783-2876<br>F:  (856) 783-3468</a></div>'
    )
    r = _parse_edlio_footer(html, "https://x.test")
    assert (r["address"], r["main_phone"]) == ("123 Parkview Road, Stratford, NJ 08084", "(856) 783-2876")
