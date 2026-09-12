-- Extends the read-only Grafana role to the tables added after the original
-- grafana_ro.sql run (2026-09-11): the survey, the page-visit counters, and
-- the community submissions inbox. Without these, the "User experience"
-- dashboard's eight SQL panels fail with "permission denied for table".
--
-- Same shape as the original script: GRANT SELECT plus a permissive SELECT
-- policy, because RLS is enabled with no policies on every table by this
-- project's Supabase defaults - a grant alone still returns zero rows.
--
-- Safe to re-run: policies are dropped first, and GRANT SELECT is idempotent.
-- Nothing here gives grafana_ro write access to anything.
--
-- Run against prod with:
--   ./scripts/alembic_env.sh prod  # (for the env), or psql "$DATABASE_URL" -f this file
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'survey_responses',
        'page_visits',
        'community_submissions'
    ]
    LOOP
        EXECUTE format('GRANT SELECT ON %I TO grafana_ro', t);
        EXECUTE format('DROP POLICY IF EXISTS grafana_ro_read ON %I', t);
        EXECUTE format('CREATE POLICY grafana_ro_read ON %I FOR SELECT TO grafana_ro USING (true)', t);
    END LOOP;
END $$;

-- Deliberately NOT granted: users, students, guardian_student_links,
-- guardian_invites, gmail_tokens, school_email_messages, notifications.
-- Nothing on a dashboard needs a family's identity, and a read-only role
-- that can read them is still a role that can leak them.
--
-- Note community_submissions.file_data (uploaded flier bytes) is readable
-- under this grant since the grant is table-wide; no panel selects it, and
-- Postgres has no column-level exclusion in this form. If that matters,
-- narrow it to GRANT SELECT (id, kind, url, status, created_at, ...).
