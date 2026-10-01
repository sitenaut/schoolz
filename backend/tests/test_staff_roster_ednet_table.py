from services.staff_roster import _parse_ednet_page

_TABLE_PAGE = """
<div id="staff" class="staffR1 staff-v-1 staff-vertical">
<div class="staff-category"><table><caption><div><h1 role="heading" aria-level="2">Administration</h1></div></caption>
<tbody><tr class="light staff-categoryStaffMember">
 <td data-label="Name :"><a href="/apps/pages/index.jsp?uREC_ID=657444&type=u">
   Mr. B. Blumenstein
 </a></td>
 <td data-label="Position :"><span>Principal</span></td>
 <td data-label="Email : "><a href="/apps/pages/index.jsp?uREC_ID=657444&type=u&pREC_ID=contact">Send E-Mail</a></td>
</tr></tbody></table></div>
<div class="staff-category"><table><caption><div><h1>Teachers</h1></div></caption>
<tbody><tr class="light staff-categoryStaffMember">
 <td data-label="Name :"><a href="/apps/pages/index.jsp?uREC_ID=111&type=u">Mrs. K. Haines</a></td>
 <td data-label="Position :"><span></span></td>
</tr></tbody></table></div>
</div>
"""


def test_ednet_table_layout_reads_name_position_and_caption_department():
    items = _parse_ednet_page(_TABLE_PAGE)
    assert [i["full_name"] for i in items] == ["Mr. B. Blumenstein", "Mrs. K. Haines"]
    assert items[0]["constituent_id"] == "ednet:657444"
    assert items[0]["title"] == "Principal"
    assert items[0]["department"] == "Administration"
    assert items[1]["title"] is None and items[1]["department"] == "Teachers"
    assert items[0]["email"] is None
