"""The HTML half of an outbound email, drawn from its plain text.

Every message is written once, as plain text (that's what's queued,
encrypted, and what a client that blocks HTML shows). At send time this
lays the same words out in Localz's dark theme - the palette of
`:root[data-section="localz"][data-theme="dark"]` in frontend/src/styles.css:

- a paragraph that ends in a link becomes a button; its line before, if it
  ends in ":", is the button's label ("Open your request:" + URL)
- "Code: 123456" becomes a large code box
- "- " lines become a list; "- text: URL" links the text
- after a "-- " line is the footer (sign-off, contact link)

Everything is escaped; nothing here comes from a template a sender controls.
Tables and inline styles only: that's what email clients render.
"""
from __future__ import annotations

import html
import re

BG = "#141a18"
CARD = "#1d2421"
INK = "#eef1f4"
INK_3 = "#838c96"
LINE = "#2c323a"
PRIMARY = "#6fc2a8"
PRIMARY_SOFT = "#1b3a31"
ACTION = "#e8875f"
ACTION_INK = "#2a1206"
FONT = "'Nunito Sans', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
FONT_D = "'Bricolage Grotesque', 'Nunito Sans', system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

URL = re.compile(r"https?://[^\s<>()]+[^\s<>().,;:!?'\"]")
CODE = re.compile(r"^Code: (\d{4,8})$")


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _links(text: str) -> str:
    """Escapes text, linking any URL in it."""
    out, last = [], 0
    for m in URL.finditer(text):
        out.append(_e(text[last : m.start()]))
        out.append(f'<a href="{_e(m.group())}" style="color:{PRIMARY};text-decoration:underline;">{_e(m.group())}</a>')
        last = m.end()
    out.append(_e(text[last:]))
    return "".join(out)


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 0;"><tr>'
        f'<td bgcolor="{ACTION}" style="border-radius:999px;background:{ACTION};">'
        f'<a href="{_e(url)}" style="display:inline-block;padding:12px 22px;font-family:{FONT};font-size:16px;'
        f'font-weight:700;color:{ACTION_INK};text-decoration:none;border-radius:999px;">{_e(label)}</a>'
        "</td></tr></table>"
    )


def _p(inner: str, color: str = INK, size: int = 16) -> str:
    return f'<p style="margin:0 0 16px;font-family:{FONT};font-size:{size}px;line-height:1.55;color:{color};">{inner}</p>'


def _block(par: str) -> str:
    lines = [ln.rstrip() for ln in par.split("\n") if ln.strip()]
    if not lines:
        return ""
    if len(lines) == 1 and (m := CODE.match(lines[0])):
        return (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px;"><tr>'
            f'<td bgcolor="{PRIMARY_SOFT}" style="background:{PRIMARY_SOFT};border:1px solid {PRIMARY};border-radius:12px;'
            f'padding:14px 22px;font-family:{FONT_D};font-size:32px;font-weight:700;letter-spacing:6px;color:{INK};">'
            f"{_e(m.group(1))}</td></tr></table>"
        )
    if all(ln.startswith("- ") for ln in lines):
        items = []
        for ln in lines:
            text = ln[2:]
            m = re.match(r"^(.*?):\s*(https?://\S+)$", text)
            inner = (
                f'<a href="{_e(m.group(2))}" style="color:{PRIMARY};font-weight:700;text-decoration:underline;">{_e(m.group(1))}</a>'
                if m
                else _links(text)
            )
            items.append(f'<li style="margin:0 0 8px;">{inner}</li>')
        return (
            f'<ul style="margin:0 0 16px;padding-left:20px;font-family:{FONT};font-size:16px;line-height:1.5;color:{INK};">'
            + "".join(items)
            + "</ul>"
        )
    if URL.fullmatch(lines[-1]):
        url, rest = lines[-1], lines[:-1]
        label = "Open on Localz"
        if rest and rest[-1].endswith(":"):
            label = rest.pop()[:-1].strip() or label
        lead = _p("<br>".join(_links(ln) for ln in rest)) if rest else ""
        return lead + f'<div style="margin:0 0 20px;">{_button(label, url)}</div>'
    return _p("<br>".join(_links(ln) for ln in lines))


def render(subject: str, text: str) -> str:
    main, _, footer = text.partition("\n-- \n")
    body = "".join(_block(p) for p in re.split(r"\n\s*\n", main.strip()))
    foot = "<br>".join(_links(ln) for ln in footer.strip().split("\n") if ln.strip())
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<title>{_e(subject)}</title>
</head>
<body style="margin:0;padding:0;background:{BG};" bgcolor="{BG}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{BG}" style="background:{BG};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
<tr><td style="padding:0 4px 14px;font-family:{FONT_D};font-size:22px;font-weight:700;color:{PRIMARY};">localz</td></tr>
<tr><td bgcolor="{CARD}" style="background:{CARD};border:1px solid {LINE};border-radius:16px;padding:28px 24px 12px;">
{body}
</td></tr>
<tr><td style="padding:16px 4px 0;font-family:{FONT};font-size:13px;line-height:1.5;color:{INK_3};">{foot}</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""

