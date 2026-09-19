"""The "I have no idea what this is about" path: five kinds of stuck, and the
email each one writes.

Why this exists at all. The dashboard answers "what do I work on now" and the
tier-A suggestion answers "how do I get started", but neither touches the case
where the student genuinely can't tell what is being asked - often because the
teacher explained it out loud in class and the Classroom description assumes
that explanation was heard, written down, and still remembered days later. The
first move there should be asking the teacher, and the reason it doesn't happen
is that composing the email is itself the barrier (Karabenick's help-seeking
work: students avoid asking in proportion to how threatening and effortful the
ask feels).

So the student never has to articulate *what* they don't understand - that's
frequently the whole problem, and asking someone to diagnose their own
confusion is a second blocker stacked on the first. They pick which KIND of
stuck they are from a short menu, and the template does the articulating, in
specific, polite, effortful-sounding words that a teacher can actually answer.

Deliberately deterministic (no model call): the wording is the product here,
it must be identical every time, and it has to work with no API key
configured. The body is handed to the client for a mailto: link - schoolz
never sends the mail itself and never stores what was sent.
"""
from __future__ import annotations

# kind -> (menu label, subject template, body template).
# Templates take {title}, {course} and {first_name}.
_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "what_to_hand_in": (
        "I don't know what we're supposed to hand in",
        "Question about {title}",
        "Hi {teacher},\n\n"
        "I'm working on {title} for {course} and I want to make sure I hand in the right thing. "
        "Could you tell me what the finished assignment should look like - is it a worksheet, a written "
        "response, a slide, or something else?\n\n"
        "Thank you,\n{first_name}",
    ),
    "dont_remember": (
        "I don't remember what we did in class about this",
        "Question about {title}",
        "Hi {teacher},\n\n"
        "I'm working on {title} for {course}. I know we went over this in class, but I didn't get it all "
        "written down and I'm having trouble remembering the part I need. Is there a place I can look it "
        "up, or could you point me to what we covered?\n\n"
        "Thank you,\n{first_name}",
    ),
    "how_to_start": (
        "I don't know how to start",
        "Question about {title}",
        "Hi {teacher},\n\n"
        "I'm trying to start {title} for {course} and I'm stuck on the first step. I've read the "
        "description but I'm not sure what to do first. Could you give me a starting point?\n\n"
        "Thank you,\n{first_name}",
    ),
    "dont_understand": (
        "I don't understand the topic itself",
        "Question about {title}",
        "Hi {teacher},\n\n"
        "I'm working on {title} for {course}, and I think the part I'm stuck on is the topic itself rather "
        "than the assignment. Could you help me understand it, or let me know a good time to come ask you "
        "about it?\n\n"
        "Thank you,\n{first_name}",
    ),
    "cant_find": (
        "I can't find the materials or the link",
        "Question about {title}",
        "Hi {teacher},\n\n"
        "I'm working on {title} for {course} and I can't find the materials for it - the link or handout "
        "doesn't seem to be somewhere I can get to. Could you point me to it?\n\n"
        "Thank you,\n{first_name}",
    ),
}

KINDS = tuple(_TEMPLATES)

# What the guardian's notification says for each kind. Deliberately reports
# only that an ask happened and of what kind - never the email body, which the
# student writes and sends from their own mail app. A parent seeing "she asked
# about what to hand in for three Geometry assignments" learns something worth
# acting on; a parent reading her mail does not.
_NOTIFICATION_PHRASES: dict[str, str] = {
    "what_to_hand_in": "what to hand in",
    "dont_remember": "what was covered in class",
    "how_to_start": "how to get started",
    "dont_understand": "understanding the topic",
    "cant_find": "where to find the materials",
}


def menu() -> list[dict[str, str]]:
    """The pick-a-kind menu, in the order it should be shown. Front-loaded
    with the two cases that are about the *assignment* being unclear rather
    than the subject being hard - those are both the most common and the
    least likely to feel like admitting you can't do the work."""
    return [{"kind": kind, "label": label} for kind, (label, _s, _b) in _TEMPLATES.items()]


def _teacher_greeting(teacher_name: str | None) -> str:
    """"Ms. Beck" stays as written; a bare "Gregory Rouen" becomes "Mr./Ms."-
    free "Gregory Rouen" rather than guessing an honorific or a gender."""
    return (teacher_name or "").strip() or "there"


def compose(kind: str, title: str, course_name: str | None, teacher_name: str | None, first_name: str) -> dict:
    """(subject, body) for one ask. Raises KeyError on an unknown kind so a
    bad client can't silently send an empty email."""
    label, subject_t, body_t = _TEMPLATES[kind]
    fields = {
        "title": f'"{title}"',
        "course": course_name or "class",
        "teacher": _teacher_greeting(teacher_name),
        "first_name": first_name,
    }
    return {
        "kind": kind,
        "label": label,
        "subject": subject_t.format(**fields),
        "body": body_t.format(**fields),
    }


def notification_message(student_first_name: str, kind: str, title: str, course_name: str | None) -> str:
    phrase = _NOTIFICATION_PHRASES.get(kind, "this assignment")
    where = f" in {course_name}" if course_name else ""
    return f'{student_first_name} asked their teacher about {phrase} for "{title}"{where}.'
