"""
Display labels for subjects.

A subject folder may carry an optional ``subject.json`` holding a human
label; without one the subject id stands in.  The demo is offered last, and a
malformed label file is refused by path and problem rather than hidden behind
the id.
"""
import pytest
from fastapi.testclient import TestClient

import bundles
import day_summary as ds
from main import app

LAMINA = "lamina_wearable"


def _write_label(folder, text):
    folder.mkdir(parents=True)
    (folder / "subject.json").write_text(text, encoding="utf-8")


def _isolate(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setattr(bundles, "BUNDLE_DIR", repo)
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(local))
    return local


def test_the_committed_subjects_carry_their_labels(monkeypatch):
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)
    labels = bundles.subject_labels()
    assert labels["subject_demo"] == "Subject demo"
    assert labels["demo"] == "Synthetic sample"


def test_a_subject_without_subject_json_gets_its_id(tmp_path, monkeypatch):
    local = _isolate(monkeypatch, tmp_path)
    (local / "plain").mkdir()

    assert bundles.subject_labels()["plain"] == "plain"


def test_a_valid_label_is_stripped(tmp_path, monkeypatch):
    local = _isolate(monkeypatch, tmp_path)
    _write_label(local / "padded", '{"label": "  Padded demo  "}')

    assert bundles.subject_labels()["padded"] == "Padded demo"


@pytest.mark.parametrize(
    "content, problem",
    [
        ("{", "invalid JSON"),
        ("[]", "must be a JSON object"),
        ("{}", "missing required field 'label'"),
        ('{"label": 3}', "label must be a string"),
        ('{"label": ""}', "must not be empty"),
        ('{"label": "   "}', "must not be empty"),
        ('{"label": "' + "x" * 41 + '"}', "at most 40 characters"),
        ('{"label": "bad\\u0001label"}', "control characters"),
    ],
)
def test_a_bad_subject_label_is_refused(
    tmp_path, monkeypatch, content, problem
):
    local = _isolate(monkeypatch, tmp_path)
    _write_label(local / "broken", content)

    with pytest.raises(ValueError) as exc:
        bundles.subject_labels()

    message = str(exc.value)
    assert str(local / "broken" / "subject.json") in message
    assert problem in message


def test_an_unreadable_subject_label_is_refused(tmp_path, monkeypatch):
    local = _isolate(monkeypatch, tmp_path)
    folder = local / "broken"
    folder.mkdir()
    (folder / "subject.json").mkdir()

    with pytest.raises(ValueError) as exc:
        bundles.subject_labels()

    message = str(exc.value)
    assert str(local / "broken" / "subject.json") in message
    assert "cannot read" in message


def test_the_demo_is_last_in_every_order(monkeypatch):
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)

    assert list(bundles.bundle_roots())[-1] == "demo"
    assert list(bundles.list_bundles())[-1] == "demo"
    assert list(bundles.subject_labels())[-1] == "demo"


def test_sources_carry_the_committed_labels(monkeypatch):
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)

    with TestClient(app) as client:
        response = client.get(f"/api/sources?lamina={LAMINA}")

    assert response.status_code == 200
    labels = response.json()["replay"]["labels"]
    assert labels["subject_demo"] == "Subject demo"
    assert labels["demo"] == "Synthetic sample"


def test_the_day_endpoint_returns_the_subject_label(monkeypatch):
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)
    ds.day_summary.cache_clear()

    with TestClient(app) as client:
        response = client.get(
            "/api/day",
            params={
                "lamina": LAMINA,
                "subject": "demo",
                "date": "2025-06-01",
            },
        )

    assert response.status_code == 200
    assert response.json()["subject_label"] == "Synthetic sample"
