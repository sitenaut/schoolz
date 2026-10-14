from services.page_flyers_parser import extract_flyers

_PAGE = """
<html><body>
<header><img src="/logo.png" width="900"></header>
<main>
<h1>Current PTA Happenings</h1>
<div class="sow-image-container"><img
  src="https://www.stjoansk-8.org/wp-content/uploads/3075B0FB.jpeg" width="1290" height="1935" srcset="x 1290w" alt=""></div>
<div class="sow-image-container"><img src="/wp-content/uploads/IMG_5586.png" width="1024" height="1536"></div>
<img src="/wp-content/uploads/icon.png" width="48">
<img src="/wp-content/uploads/3075B0FB.jpeg" width="1290">
<img src="data:image/png;base64,AAAA" width="900">
<img src="/wp-content/uploads/anim.gif" width="900">
</main>
<footer><img src="/footer.jpg" width="900"></footer>
</body></html>
"""


def test_flyers_are_the_large_content_images_once_each():
    items = extract_flyers(_PAGE, "https://www.stjoansk-8.org/pta-1/")
    assert [i["image_url"] for i in items] == [
        "https://www.stjoansk-8.org/wp-content/uploads/3075B0FB.jpeg",
        "https://www.stjoansk-8.org/wp-content/uploads/IMG_5586.png",
    ]
    assert all(i["block_type"] == "image" for i in items)
    assert len({i["content_hash"] for i in items}) == 2
