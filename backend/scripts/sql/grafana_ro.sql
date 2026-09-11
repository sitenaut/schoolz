-- Read-only role for the Grafana Cloud PostgreSQL datasource ("schoolz-prod-db").
-- Run once by hand in the Supabase SQL editor against prod. NOT an Alembic
-- migration: it holds a password and the role doesn't exist locally.
-- See docs/OBSERVABILITY_PLAN.md, Phase 1.
--
-- RLS is on with no policies on every table by project default, so without
-- an explicit SELECT policy a non-owner role sees zero rows even after GRANT.
--
-- Deliberately excluded (PII / credentials): users, students,
-- guardian_student_links, guardian_invites, gmail_tokens, email_scanners,
-- email_scanner_matches, school_email_messages, notifications.

CREATE ROLE grafana_ro LOGIN PASSWORD '<PASSWORD>';
ALTER ROLE grafana_ro SET statement_timeout = '15s';
GRANT USAGE ON SCHEMA public TO grafana_ro;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'scheduled_jobs', 'job_runs', 'districts', 'schools', 'smore_newsletters',
        'smore_blocks', 'school_content_items', 'school_documents', 'staff_members',
        'lunch_menus', 'lunch_menu_items', 'sacc_programs', 'district_transportation'
    ]
    LOOP
        EXECUTE format('GRANT SELECT ON %I TO grafana_ro', t);
        EXECUTE format('CREATE POLICY grafana_ro_read ON %I FOR SELECT TO grafana_ro USING (true)', t);
    END LOOP;
END $$;
