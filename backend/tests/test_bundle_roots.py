"""
Which subject folders the replay offers.

Committed subjects under bundles/ are offered without any environment set, so
a deployment that only has the repository (Render) still serves them; the
environment's folder of the same name wins, except for the demo.
"""
import bundles


def _subject(base, name):
    folder = base / name
    folder.mkdir(parents=True)
    return folder


def test_committed_subjects_are_offered_without_the_environment(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _subject(repo, "demo")
    s7 = _subject(repo, "s7")
    monkeypatch.setattr(bundles, "BUNDLE_DIR", repo)
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)

    roots = bundles.bundle_roots()

    assert roots["demo"] == repo / "demo"
    assert roots["s7"] == s7


def test_a_folder_that_is_not_a_subject_id_is_ignored(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _subject(repo, "demo")
    _subject(repo, "Not A Subject")
    (repo / "bundle.schema.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(bundles, "BUNDLE_DIR", repo)
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)

    assert set(bundles.bundle_roots()) == {"demo"}


def test_the_environment_replaces_a_committed_subject_but_never_the_demo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _subject(repo, "demo")
    _subject(repo, "s7")
    local = tmp_path / "local"
    _subject(local, "demo")
    local_s7 = _subject(local, "s7")
    local_s8 = _subject(local, "s8")
    monkeypatch.setattr(bundles, "BUNDLE_DIR", repo)
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(local))

    roots = bundles.bundle_roots()

    assert roots["demo"] == repo / "demo"
    assert roots["s7"] == local_s7
    assert roots["s8"] == local_s8


def test_the_published_subject_is_offered_from_the_repository(monkeypatch):
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)
    listing = bundles.list_bundles()
    assert "s2" in listing and len(listing["s2"]) > 0
    assert bundles.load_params("s2") is not None
