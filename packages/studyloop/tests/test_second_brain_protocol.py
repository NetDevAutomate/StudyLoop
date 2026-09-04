"""T1 C1/C2: the SecondBrain protocol's shape and its result types.

The method-set guard exists for the same reason ``test_multiplexer_protocol.py``
has one: a Protocol is the contract every backend must satisfy, so a method
added to it in passing silently obliges every future backend (and every
contract test) to grow without anyone deciding to. Pinning the exact set makes
that a red test rather than a surprise.
"""

from __future__ import annotations

import inspect

import pytest

from studyloop.second_brain.core import (
    BrainDescription,
    NullBackend,
    PublishResult,
    PullNotesResult,
    SecondBrain,
    SecondBrainError,
    XtilesStageOneBackend,
)

EXPECTED_METHODS = frozenset(
    {
        "describe",
        "is_available",
        "publish_plan",
        "publish_today",
        "publish_learning_record",
        "pull_notes",
    }
)


def _public_protocol_methods(protocol: type) -> frozenset[str]:
    """Every public method the Protocol itself declares."""
    return frozenset(
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and inspect.isfunction(value)
    )


def test_protocol_is_runtime_checkable() -> None:
    assert isinstance(NullBackend(), SecondBrain)
    assert isinstance(XtilesStageOneBackend(), SecondBrain)
    assert not isinstance(object(), SecondBrain)


def test_protocol_has_exact_public_method_set() -> None:
    assert _public_protocol_methods(SecondBrain) == EXPECTED_METHODS


def test_second_brain_error_is_an_exception() -> None:
    assert issubclass(SecondBrainError, Exception)


def test_publish_result_json_shape() -> None:
    result = PublishResult(
        provider="obsidian",
        operation="publish_plan",
        written=("Study/Plans/python-decorators.md",),
        unchanged=(),
        skipped=(),
        warnings=("something to say",),
    )
    payload = result.to_json_dict()
    assert set(payload) == {
        "provider",
        "operation",
        "written",
        "unchanged",
        "skipped",
        "warnings",
    }
    assert payload["written"] == ["Study/Plans/python-decorators.md"]
    assert payload["unchanged"] == []
    assert payload["warnings"] == ["something to say"]


def test_pull_notes_result_json_shape() -> None:
    payload = PullNotesResult(
        provider="obsidian",
        plan_id="python-decorators",
        found=True,
        notes="my own thoughts",
        sources=("Study/Plans/python-decorators.notes.md",),
    ).to_json_dict()
    assert set(payload) == {
        "provider",
        "plan_id",
        "found",
        "notes",
        "sources",
        "warnings",
    }
    assert payload["found"] is True
    assert payload["sources"] == ["Study/Plans/python-decorators.notes.md"]


@pytest.mark.parametrize(
    "bad_path",
    [
        pytest.param("/tmp/out.md", id="posix-absolute"),
        pytest.param("C:\\vault\\out.md", id="windows-absolute"),
    ],
)
def test_results_reject_absolute_reported_paths(bad_path: str) -> None:
    """No ``brain`` JSON may leak an absolute path except ``status.vault_path``.

    A published path is vault-relative, so an absolute one means the caller
    reported a filesystem location that identifies the machine and its user —
    the class of leak the public-hygiene rules exist to prevent.
    """
    with pytest.raises(ValueError, match="vault-relative"):
        PublishResult(
            provider="obsidian", operation="publish_plan", written=(bad_path,)
        ).to_json_dict()
    with pytest.raises(ValueError, match="vault-relative"):
        PullNotesResult(
            provider="obsidian", plan_id="x", found=True, sources=(bad_path,)
        ).to_json_dict()


def test_brain_description_json_has_exactly_eight_keys() -> None:
    payload = BrainDescription(
        provider="none",
        configured=False,
        available=False,
        supports_publish=False,
        supports_pull_notes=False,
        vault_path=None,
        folder=None,
        detail="Second brain is not configured.",
    ).to_json_dict()
    assert set(payload) == {
        "provider",
        "configured",
        "available",
        "supports_publish",
        "supports_pull_notes",
        "vault_path",
        "folder",
        "detail",
    }
    assert all(isinstance(payload[k], bool) for k in ("configured", "available"))
