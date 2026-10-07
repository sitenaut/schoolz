from services import staff_roster

GRID = """
<ul><li data-filter=".uabb-masonary-cat-69">Administration</li><li data-filter=".uabb-masonary-cat-68">Support Staff</li></ul>
<div class="uabb-post-wrapper uabb-masonary-cat-69">
  <a href="https://d.test/staff-member/pat-lee/"><img alt="Pat Lee"></a>
  <h3 class="uabb-post-heading"><a href="https://d.test/staff-member/pat-lee/">Pat Lee</a></h3>
  <div>Principal</div><span class="uabb-read-more-text"><a href="https://d.test/staff-member/pat-lee/">Read Bio »</a></span>
</div>
<div class="uabb-post-wrapper">
  <h3 class="uabb-post-heading"><a href="https://d.test/staff-member/sam-roe/">Sam Roe</a></h3><div>Music Teacher</div>
</div>
"""


def _profile(name, locations, email):
    locs = "".join(f"<div>{loc}</div>" for loc in locations)
    return (
        f"<nav>{name}</nav><main><h1>{name}</h1><div>Grade(s)/Department:</div><div>Administration</div>"
        f"<div>Title(s):</div><div>Principal</div><div>Location(s):</div>{locs}<div>{email}</div>"
        "<a>Staff Directory</a><a>Staff Bio</a></main>"
    )


def test_grid_reads_name_title_and_department():
    people = staff_roster._parse_wp_staff_grid(GRID)
    assert [(p["constituent_id"], p["full_name"], p["title"], p["department"]) for p in people] == [
        ("wpstaff:pat-lee", "Pat Lee", "Principal", "Administration"),
        ("wpstaff:sam-roe", "Sam Roe", "Music Teacher", None),
    ]


def test_profile_reads_every_location_and_the_email():
    one = staff_roster._parse_wp_staff_profile(_profile("Pat Lee", ["Dwight D. Eisenhower"], "plee@d.test"), "Pat Lee")
    assert one == {"locations": ["Dwight D. Eisenhower"], "email": "plee@d.test", "phone": None}
    both = staff_roster._parse_wp_staff_profile(_profile("Sam Roe", ["Dwight D. Eisenhower", "John F. Kennedy"], "SROE@D.TEST"), "Sam Roe")
    assert both == {"locations": ["Dwight D. Eisenhower", "John F. Kennedy"], "email": "sroe@d.test", "phone": None}


def test_profile_decodes_cloudflare_email_and_reads_phone():
    # What plain HTTP gets: the address is hidden behind data-cfemail.
    key = 0x2A
    hidden = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in "plee@d.test")
    html = (
        "<main><h1>Pat Lee</h1><div>Title(s):</div><div>Principal</div><div>Location(s):</div><div>District</div>"
        f'<a href="/cdn-cgi/l/email-protection"><span data-cfemail="{hidden}">[email&#160;protected]</span></a>'
        "<div>(856) 767-9480 ext. 1111</div><a>Staff Directory</a></main>"
    )
    assert staff_roster._parse_wp_staff_profile(html, "Pat Lee") == {
        "locations": ["District"],
        "email": "plee@d.test",
        "phone": "(856) 767-9480 ext. 1111",
    }


def test_locations_decide_which_school_keeps_a_person():
    def person(cid, locations):
        return {"constituent_id": cid, "title": "Teacher", "locations": locations}

    roster = [person("e", ["Dwight D. Eisenhower"]), person("k", ["John F. Kennedy"]), person("both", ["Dwight D. Eisenhower", "John F. Kennedy"]), person("office", [])]
    kept, dropped = staff_roster.drop_sibling_school_staff(
        roster, ["Kennedy", "John F. Kennedy Elementary School"], [["Eisenhower", "Dwight D. Eisenhower Middle School"]]
    )
    assert [p["constituent_id"] for p in kept] == ["k", "both", "office"]
    assert [p["constituent_id"] for p in dropped] == ["e"]
