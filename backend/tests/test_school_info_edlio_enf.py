from services.school_info import _parse_edlio_footer


def test_edlio_enf_address_footer_reads_address_and_plain_text_phone():
    html = (
        '<div class="enf-address"><a href="/apps/maps" target="_blank">'
        "123 Parkview Road <br/>\n    Stratford, NJ 08084\n</a>"
        '<a href="/apps/contact">P:  (856) 783-2876<br>F:  (856) 783-3468</a></div>'
    )
    r = _parse_edlio_footer(html, "https://x.test")
    assert (r["address"], r["main_phone"]) == ("123 Parkview Road, Stratford, NJ 08084", "(856) 783-2876")


def test_edlio_enf_address_collapses_a_line_break_inside_one_text_node():
    # Rancocas Valley: street and town are one text node split by a newline.
    html = (
        '<div class="enf-address"><a href="/apps/maps">520 Jacksonville Road,\n            Mt. Holly, NJ 08060</a>'
        '<a href="/apps/contact">P: (609) 267-0830</a></div>'
    )
    assert _parse_edlio_footer(html, "https://x.test")["address"] == "520 Jacksonville Road, Mt. Holly, NJ 08060"


def test_edlio_footer_with_a_trailing_slash_map_link_and_a_stray_keystroke():
    # Jersey City's hosts: "/apps/maps/", and PS 12 typed a backtick into its number.
    html = (
        '<div class="footer-info-block address"><a href="/apps/maps/">91 Astor Place<br>Jersey City, NJ 07304</a></div>'
        '<div class="footer-info-block phone"><a href="tel:2019156420">201-9`15-6420</a></div>'
    )
    r = _parse_edlio_footer(html, "https://ps12.jcboe.org")
    assert (r["address"], r["main_phone"]) == ("91 Astor Place Jersey City, NJ 07304", "201-915-6420")
