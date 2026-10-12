"""validation/second_opinion_claude.py with a stubbed HTTP layer: nothing here calls Anthropic."""

import json
import os
import sys

import pandas as pd
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validation"))
import second_opinion_claude as so  # noqa: E402

REPLY = {
    "solar_present": False, "solar_area_m2": None, "solar_confidence": 0.8,
    "portables_count": 1, "portables_confidence": 0.5,
    "fence_status": "full", "fence_type": "chain-link", "fence_confidence": 0.6,
    "track_present": True, "track_confidence": 0.9,
    "sports_fields_list": ["football field"], "sports_fields_count": 1, "sports_fields_confidence": 0.6,
    "hard_courts_list": [], "hard_courts_count": 0, "hard_courts_confidence": 0.5,
    "pool_present": False, "pool_confidence": 0.9, "notes": "",
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.headers = payload, status, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._payload


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return str(path)


def test_call_claude_sends_the_same_prompt_and_an_image_and_parses_fenced_json(png, monkeypatch):
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)
        text = "```json\n" + __import__("json").dumps(REPLY) + "\n```"
        return FakeResponse({"content": [{"type": "text", "text": text}],
                             "usage": {"input_tokens": 1500, "output_tokens": 200}})

    monkeypatch.setattr(so.requests, "post", fake_post)
    monkeypatch.setattr(so.config, "ANTHROPIC_API_KEY", "test-key")
    parsed, usage = so.call_claude(png, 0.6, True, "matched an OSM school-grounds polygon")

    assert parsed["track_present"] is True and usage["input_tokens"] == 1500
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["x-api-key"] == "test-key"
    assert "test-key" not in sent["url"]                      # header auth, never in the URL
    content = sent["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert sent["body"]["temperature"] == 0
    # identical prompt text to the primary pipeline's (same builder, same inputs)
    from vision_extract import _build_prompt
    assert content[1]["text"] == _build_prompt(0.6, True, "matched an OSM school-grounds polygon")
    assert "hard_courts_list" in content[1]["text"]           # the same schema is requested


def test_call_claude_retries_then_raises(png, monkeypatch):
    calls = []
    monkeypatch.setattr(so.requests, "post", lambda *a, **k: calls.append(1) or FakeResponse({}, status=500))
    monkeypatch.setattr(so.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        so.call_claude(png, 0.6, False, "n", attempts=3)
    assert len(calls) == 3


def _primary():
    return pd.DataFrame({
        "school_id": ["1", "2"], "vision_model": ["gpt-5.4", "gpt-5.4"],
        "solar_present": ["False", "True"], "portables_count": [0, 3], "fence_status": ["partial", "full"],
        "track_present": ["True", "False"], "sports_fields_count": [2, 1], "hard_courts_count": [1, 4],
        "pool_present": ["False", "False"],
    })


def _claude():
    return pd.DataFrame({
        "school_id": ["1", "2"], "model": ["claude-x", "claude-x"],
        "solar_present": [False, False], "portables_count": [0, 1], "fence_status": ["partial", "full"],
        "track_present": [True, False], "sports_fields_count": [2, 3], "hard_courts_count": [3, 4],
        "pool_present": [False, False],
    })


def test_agreement_by_hand():
    summary, detail = so.agreement(_primary(), _claude())
    by_field = summary.set_index("field")
    # solar: school 1 agrees, school 2 (True vs False) does not
    assert by_field.loc["solar_present", "agreement"] == 0.5
    assert by_field.loc["fence_status", "agreement"] == 1.0
    assert by_field.loc["track_present", "agreement"] == 1.0
    assert by_field.loc["pool_present", "agreement"] == 1.0
    # portables: |0-0| and |3-1|; sports: |2-2| and |1-3|; hard courts: |1-3| and |4-4|
    assert by_field.loc["portables_count", ["agreement", "mean_abs_diff"]].tolist() == [0.5, 1.0]
    assert by_field.loc["sports_fields_count", ["agreement", "mean_abs_diff"]].tolist() == [0.5, 1.0]
    assert by_field.loc["hard_courts_count", ["agreement", "mean_abs_diff"]].tolist() == [0.5, 1.0]
    assert len(detail) == 14 and detail["agree"].sum() == 10


def test_agreement_ignores_schools_missing_from_the_primary():
    extra = pd.concat([_claude(), _claude().assign(school_id=["9", "9"])])
    _, detail = so.agreement(_primary(), extra)
    assert set(detail["school_id"]) == {"1", "2"}


def test_main_refuses_without_a_key_and_sends_nothing(monkeypatch, capsys):
    monkeypatch.setattr(so.config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(so.os.path, "exists", lambda p: True)  # pretend every cached image is there
    monkeypatch.setattr(so.requests, "post", lambda *a, **k: pytest.fail("must not call the API"))
    monkeypatch.setattr(sys, "argv", ["second_opinion_claude.py", "--limit", "2"])
    assert so.main() == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_main_end_to_end_with_a_stubbed_api_writes_the_csv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(so.config, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(so.os.path, "exists", lambda p: True)
    monkeypatch.setattr(so.time, "sleep", lambda s: None)
    monkeypatch.setattr(so, "OUT_PATH", str(tmp_path / "out.csv"))
    monkeypatch.setattr(so, "call_claude", lambda *a, **k: (dict(REPLY), {"input_tokens": 10, "output_tokens": 5}))
    monkeypatch.setattr(sys, "argv", ["second_opinion_claude.py", "--limit", "2"])
    assert so.main() == 0
    written = pd.read_csv(tmp_path / "out.csv", dtype={"school_id": str})
    assert list(written.columns) == so.CSV_COLUMNS
    assert len(written) == 2 and (written["model"] == so.config.CLAUDE_MODEL).all()
    assert "Overall agreement" in capsys.readouterr().out
