"""The migration rails: the additive check CI runs, and the release step's plan."""
import importlib.util
from pathlib import Path

_SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load("check_migrations_additive")
release = _load("release")

ADDITIVE = '''
def upgrade():
    op.add_column("t", sa.Column("c", sa.Text(), nullable=True))
    op.execute("UPDATE t SET c = 'x'")

def downgrade():
    op.drop_column("t", "c")
    op.execute("DELETE FROM t WHERE c = 'x'")
'''

DESTRUCTIVE = '''
def upgrade():
    op.drop_column("t", "old")
    op.execute("""
        delete   from t where stale
    """)
    op.execute(sa.text("TRUNCATE other"))
'''


def test_an_additive_revision_passes_and_downgrade_is_not_judged():
    assert check.findings(ADDITIVE) == []


def test_drops_deletes_and_truncates_in_upgrade_are_found():
    found = check.findings(DESTRUCTIVE)
    assert [f.split(": ", 1)[1] for f in found] == ["op.drop_column", "SQL DELETE FROM", "SQL TRUNCATE"]


def test_the_marker_lets_a_revision_through(tmp_path, capsys):
    path = tmp_path / "0999_x.py"
    path.write_text(DESTRUCTIVE)
    assert check.main([str(path)]) == 1
    path.write_text("# destructive-ok: merging duplicates; backup schoolz-29990101T000000Z\n" + DESTRUCTIVE)
    assert check.main([str(path)]) == 0
    assert "allowed by its destructive-ok note" in capsys.readouterr().out


def test_an_empty_marker_does_not_count(tmp_path):
    path = tmp_path / "0999_x.py"
    path.write_text("# destructive-ok:\n" + DESTRUCTIVE)
    assert check.main([str(path)]) == 1


def test_the_current_revisions_pass():
    assert check.main([]) == 0


def test_release_plan():
    known = {"0098", "0099"}
    assert release.plan(set(), known, ["0099"]) == "upgrade"
    assert release.plan({"0098"}, known, ["0099"]) == "upgrade"
    assert release.plan({"0099"}, known, ["0099"]) == "current"
    # An older image redeployed (a rollback) never touches a newer database.
    assert release.plan({"0100"}, known, ["0099"]) == "ahead"
    assert release.plan({"0099"}, known, ["0098", "0099"]) == "bad_heads"
