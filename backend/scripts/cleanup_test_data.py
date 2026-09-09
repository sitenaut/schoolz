"""Deletes rows the pytest suite leaves behind in the shared local
database (see CLAUDE.md: "Known local-dev footgun"). Tests run against
the same Postgres as `docker-compose.local.yml`, not an isolated
database, so every `pytest -q` locally adds another batch of throwaway
users/students/schools unless this is run afterward.

Safe by construction: test users always register with an `@example.com`
email (see tests/test_students.py's `_register` helper) - never a real
domain - and test schools/districts/scheduled jobs are always named
"Test ..." (e.g. "Test Elementary <hex>", "Test District <hex>",
"Smore scan: Test Weekly"). Nothing matching a real account, school, or
job can match either filter.

Usage: python scripts/cleanup_test_data.py  (run from backend/, same
DATABASE_* env as the API - works against docker-compose.local.yml's
postgres service without changes)
"""

import asyncio
import sys
from pathlib import Path

# Runnable regardless of cwd - Python only auto-adds the *script's own*
# directory to sys.path, not the backend/ package root it needs to
# import `database` from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from database import engine


async def main() -> None:
    deleted: dict[str, int] = {}
    async with engine.begin() as conn:
        # Every table with a user FK (ON DELETE NO ACTION, so deleting a
        # test user below would otherwise fail if any of these still
        # reference it) that isn't itself deleted as "the test user's own
        # data" gets its owner/creator reference cleared first. Rows that
        # ARE the user's own data (links, notifications, invites) are
        # deleted outright further down instead.
        for label, stmt in [
            ("schools.created_by_user_id cleared", "UPDATE schools SET created_by_user_id = NULL WHERE created_by_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            ("smore_newsletters.created_by_user_id cleared", "UPDATE smore_newsletters SET created_by_user_id = NULL WHERE created_by_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            ("scheduled_jobs.owner_user_id cleared", "UPDATE scheduled_jobs SET owner_user_id = NULL WHERE owner_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            ("email_scanners.owner_user_id cleared", "UPDATE email_scanners SET owner_user_id = NULL WHERE owner_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            ("school_email_messages.owner_user_id cleared", "UPDATE school_email_messages SET owner_user_id = NULL WHERE owner_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
        ]:
            result = await conn.execute(text(stmt))
            deleted[label] = result.rowcount

        for label, stmt in [
            ("guardian_student_links", "DELETE FROM guardian_student_links WHERE guardian_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            ("notifications", "DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            (
                "guardian_invites",
                "DELETE FROM guardian_invites WHERE inviter_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com') "
                "OR accepted_by_user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')",
            ),
            ("gmail_tokens", "DELETE FROM gmail_tokens WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com')"),
            ("users", "DELETE FROM users WHERE email LIKE '%@example.com'"),
            ("orphaned students", "DELETE FROM students WHERE id NOT IN (SELECT DISTINCT student_id FROM guardian_student_links)"),
            # Test-created scheduled jobs (e.g. "Smore scan: Test Weekly",
            # "Transportation scan: Test District <hex>") aren't cascaded
            # from anything - scheduled_jobs has no real FK to schools/
            # districts (they're referenced by id inside a JSON `params`
            # column), so these would otherwise linger forever even after
            # the school/district itself is deleted below.
            ("test-named scheduled jobs", "DELETE FROM scheduled_jobs WHERE name LIKE 'Test %' OR name LIKE '%: Test %'"),
            ("test-named smore newsletters", "DELETE FROM smore_newsletters WHERE label LIKE 'Test %'"),
            ("test schools", "DELETE FROM schools WHERE name ILIKE 'Test %'"),
            ("test districts", "DELETE FROM districts WHERE name ILIKE 'Test %'"),
        ]:
            result = await conn.execute(text(stmt))
            deleted[label] = result.rowcount

    for label, count in deleted.items():
        print(f"{label}: {count} deleted")


if __name__ == "__main__":
    asyncio.run(main())
