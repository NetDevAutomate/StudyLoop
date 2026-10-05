"""The core-created disposable kind cluster for ``target.kind: kubeconfig-context`` (lane K0).

Offline by construction (C4): a fake ``kind`` shell script on a scratch PATH records every
argv it receives (one tab-separated line per call in ``$FAKE_KIND_LOG``), writes a
TWO-context kubeconfig at ``--kubeconfig`` (the disposable cluster's context beside a
learner-looking one, so the one-context rewrite has something to remove), answers
``get clusters`` from ``$FAKE_KIND_CLUSTERS``, and honours ``FAKE_KIND_FAIL=create|delete`` and
``FAKE_KIND_HANG=create``. A fake ``kubectl`` prints the ``KUBECONFIG`` it was given and the
``current-context`` of that file; a fake ``docker`` exits 0. The scratch PATH is
``<fake bin>:/usr/bin:/bin`` -- the learner's real PATH is never consulted, so a real ``kind``
installed on this machine cannot be reached by accident.

Spec (``specs/drill-runner/spec.md``, "A kubeconfig-context attempt runs against a core-created
disposable cluster") and brief (``briefs/K0-cluster-provisioning.md``) items pinned here:

- provision argv exactly as specified -- a list, the resolved ``kind`` path, ``shell=False``,
  stdin ``DEVNULL``, ``start_new_session=True``;
- the kubeconfig is rewritten to exactly one context and ``0o600``;
- the name derives from the attempt id with the ``studyloop-`` prefix; a collision is refused;
- teardown argv, the kubeconfig removed, and a teardown failure surfacing as an error naming
  the cluster; a failed or hung create never leaves a half-made cluster behind silently.

The second half drives ``studyloop drill`` with ``CliRunner`` against the ``k8s-offline``
fixture module (``tests/fixtures/modules/k8s-offline/``, a ``kubeconfig-context`` drill whose
scripts only echo ``$KUBECONFIG`` and read ``kubectl config current-context``): ``setup``
provisions before the consent prompt and the prompt names the cluster, the child sees
``KUBECONFIG=<attempt>/kubeconfig``, ``check`` reuses it, ``cleanup`` deletes after the module's
script, and every failure path after a successful create -- declined consent, failed setup,
check timeout, Ctrl-C -- tears the cluster down; the pre-consent refusals (missing core tool,
name collision, check with nothing open) never call ``kind create``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from click.testing import CliRunner
from test_module_drill_cli import _events, _module_digest
from test_module_runner import SpawnCall, spawn_spy
from test_practice_verify import _attempt_db, _patch_db

from studyloop.cli import _drill
from studyloop.cli._drill import drill_group
from studyloop.modules import cluster, runner
from studyloop.modules.attempt import (
    Attempt,
    AttemptStore,
    DrillIdentity,
    InstalledModule,
    TargetKind,
)
from studyloop.modules.cluster import ClusterError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["spawn_spy"]  # re-exported pytest fixture from test_module_runner

FAKE_KIND = textwrap.dedent(
    """\
    #!/bin/sh
    # Fake kind for the offline K0 tests. Records argv; never touches Docker.
    #   FAKE_KIND_FAIL=create             create exits 1 BEFORE writing the kubeconfig
    #   FAKE_KIND_FAIL=create-registered  same, but the name then appears in `get clusters`
    #                                     (a cluster core cannot prove it created)
    #   FAKE_KIND_FAIL=create-after-write create writes the kubeconfig, then exits 1
    #                                     (the `--wait` timeout shape)
    #   FAKE_KIND_FAIL=misname            create exits 0 but the contexts are not kind-<name>
    #   FAKE_KIND_FAIL=malformed          create exits 0 but `contexts:` holds non-mappings
    #   FAKE_KIND_FAIL=delete             delete exits 1
    #   FAKE_KIND_FAIL_DELETE=1           delete exits 1 (combinable with a create mode)
    #   FAKE_KIND_HANG=create             create writes the kubeconfig, then sleeps 30 s
    #   FAKE_KIND_CLUSTERS="a b"          what `get clusters` lists (plus registered names)
    set -u
    log="${FAKE_KIND_LOG:?FAKE_KIND_LOG must be set}"
    { for arg in "$@"; do printf '%s\\t' "$arg"; done; printf '\\n'; } >> "$log"
    env | sort > "$log.env.$(wc -l < "$log" | tr -d ' ')"
    case "${1:-} ${2:-}" in
      "get clusters")
        if [ -n "${FAKE_KIND_CLUSTERS:-}" ]; then
          for name in $FAKE_KIND_CLUSTERS; do printf '%s\\n' "$name"; done
        fi
        if [ -f "$log.registered" ]; then cat "$log.registered"; fi
        if [ -z "${FAKE_KIND_CLUSTERS:-}" ] && [ ! -f "$log.registered" ]; then
          echo "No kind clusters found." >&2
        fi
        exit 0 ;;
      "create cluster")
        name=""; kubeconfig=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --name) name="$2"; shift ;;
            --kubeconfig) kubeconfig="$2"; shift ;;
          esac
          shift
        done
        if [ "${FAKE_KIND_FAIL:-}" = create ]; then
          echo "fake kind: create failed on purpose" >&2
          exit 1
        fi
        if [ "${FAKE_KIND_FAIL:-}" = create-registered ]; then
          printf '%s\\n' "$name" >> "$log.registered"
          echo "fake kind: create failed on purpose (but the cluster is listed)" >&2
          exit 1
        fi
        context="kind-$name"
        if [ "${FAKE_KIND_FAIL:-}" = misname ]; then context="kind-somebody-else"; fi
        contexts="- name: $context
      context: {cluster: $context, user: $context}
    - name: learner-prod
      context: {cluster: learner-prod, user: learner-admin}"
        if [ "${FAKE_KIND_FAIL:-}" = malformed ]; then contexts="- 1
    - 2"; fi
        cat > "$kubeconfig" <<EOF
    apiVersion: v1
    kind: Config
    preferences: {}
    clusters:
    - name: $context
      cluster: {server: 'https://127.0.0.1:6443'}
    - name: learner-prod
      cluster: {server: 'https://learner.example:6443'}
    contexts:
    $contexts
    current-context: $context
    users:
    - name: $context
      user: {username: $context}
    - name: learner-admin
      user: {username: learner-admin}
    EOF
        if [ "${FAKE_KIND_HANG:-}" = create ]; then sleep 30; fi
        if [ "${FAKE_KIND_FAIL:-}" = create-after-write ]; then
          echo "fake kind: control plane never became ready (wait timed out)" >&2
          exit 1
        fi
        echo "Creating cluster \\"$name\\" ... (fake)"
        exit 0 ;;
      "delete cluster")
        if [ "${FAKE_KIND_FAIL:-}" = delete ] || [ -n "${FAKE_KIND_FAIL_DELETE:-}" ]; then
          echo "fake kind: delete failed on purpose" >&2
          exit 1
        fi
        exit 0 ;;
    esac
    echo "fake kind: unexpected argv: $*" >&2
    exit 64
    """
)

FAKE_KUBECTL = textwrap.dedent(
    """\
    #!/bin/sh
    # Fake kubectl: prints the KUBECONFIG it sees; `config current-context` reads that file.
    set -u
    if [ "${1:-}" = config ] && [ "${2:-}" = current-context ]; then
      sed -n 's/^current-context: //p' "${KUBECONFIG:?KUBECONFIG is not set}"
      exit 0
    fi
    echo "kubectl KUBECONFIG=${KUBECONFIG:-<unset>}"
    exit 0
    """
)

FAKE_DOCKER = "#!/bin/sh\nexit 0\n"


@dataclass
class FakeTools:
    """The scratch ``bin/`` holding the fakes, and the fake kind's argv log."""

    bin_dir: Path
    log: Path

    def calls(self) -> list[list[str]]:
        """Every fake-kind invocation's argv, oldest first (``[]`` when kind never ran)."""
        if not self.log.exists():
            return []
        return [
            line.rstrip("\t").split("\t")
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def kind_env(self) -> list[dict[str, str]]:
        """The environment the fake kind saw, one mapping per invocation (oldest first)."""
        dumps = sorted(
            self.log.parent.glob(f"{self.log.name}.env.*"), key=lambda p: int(p.suffix[1:])
        )
        result: list[dict[str, str]] = []
        for dump in dumps:
            env: dict[str, str] = {}
            for line in dump.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep:
                    env[key] = value
            result.append(env)
        return result

    @property
    def kind(self) -> Path:
        return (self.bin_dir / "kind").resolve()


@pytest.fixture
def fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeTools:
    """Fake ``kind``/``kubectl``/``docker`` first and alone on a scratch PATH."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for name, body in (("kind", FAKE_KIND), ("kubectl", FAKE_KUBECTL), ("docker", FAKE_DOCKER)):
        script = bin_dir / name
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
    log = tmp_path / "kind-calls.log"
    monkeypatch.setenv("FAKE_KIND_LOG", str(log))
    for var in (
        "FAKE_KIND_FAIL",
        "FAKE_KIND_FAIL_DELETE",
        "FAKE_KIND_HANG",
        "FAKE_KIND_CLUSTERS",
        "KUBECONFIG",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return FakeTools(bin_dir=bin_dir, log=log)


@pytest.fixture
def tools(fake_tools: FakeTools) -> Mapping[str, Path]:
    """What ``_drill`` hands ``provision``: core's three tools resolved on the (scratch) PATH."""
    resolved = runner.resolve_prerequisites(cluster.CLUSTER_TOOLS)
    assert resolved["kind"] == fake_tools.kind, "the fake kind must be the one resolved"
    return resolved


@pytest.fixture
def attempt(tmp_path: Path) -> Attempt:
    """An open ``kubeconfig-context`` attempt with no kubeconfig yet (what ``setup`` opens)."""
    drill = DrillIdentity(
        module_id="k8s-offline",
        module_digest="sha256:" + "0" * 64,
        deck_id="cluster",
        task_id="current-context",
    )
    store = AttemptStore(root=tmp_path / "module-attempts")
    return store.open(drill, snapshot_dir=tmp_path, target=TargetKind.KUBECONFIG_CONTEXT)


def _expected_name(attempt: Attempt) -> str:
    return f"studyloop-{attempt.attempt_id[:8]}"


def _kind_spawns(spawn_spy: list[SpawnCall], fake_tools: FakeTools) -> list[SpawnCall]:
    return [call for call in spawn_spy if Path(call.args[0]) == fake_tools.kind]


# ---------------------------------------------------------------------------
# provision
# ---------------------------------------------------------------------------


def test_provision_spawns_kind_create_with_the_exact_argv_and_no_shell(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    spawn_spy: list[SpawnCall],
) -> None:
    """Brief item 1: ``kind create cluster --name studyloop-<prefix> --kubeconfig
    <attempt>/kubeconfig --wait 120s`` through the RESOLVED binary, as a list, ``shell=False``,
    stdin ``DEVNULL``, ``start_new_session=True``. The only other kind call is the read-only
    ``get clusters`` that refuses a name collision (item 4)."""
    handle = cluster.provision(attempt, tools=tools)

    name = _expected_name(attempt)
    kubeconfig = attempt.attempt_dir / "kubeconfig"
    assert handle.name == name
    assert handle.kubeconfig == kubeconfig
    assert fake_tools.calls() == [
        ["get", "clusters"],
        ["create", "cluster", "--name", name, "--kubeconfig", str(kubeconfig), "--wait", "120s"],
    ]
    spawns = _kind_spawns(spawn_spy, fake_tools)
    assert len(spawns) == 2, "one listing, one create -- nothing else"
    create = spawns[1]
    assert isinstance(create.args, list)
    assert create.args == [
        str(fake_tools.kind),
        "create",
        "cluster",
        "--name",
        name,
        "--kubeconfig",
        str(kubeconfig),
        "--wait",
        "120s",
    ]
    assert Path(create.args[0]).is_absolute(), "argv[0] is the resolved kind, not a PATH lookup"
    for call in spawns:
        assert call.kwargs.get("shell", False) is False
        assert call.kwargs.get("stdin") is subprocess.DEVNULL
        assert call.kwargs.get("start_new_session") is True


def test_provision_rewrites_the_kubeconfig_to_exactly_one_context_mode_0600(
    attempt: Attempt, tools: Mapping[str, Path], fake_tools: FakeTools
) -> None:
    """§5.5 *Kubernetes identity*: the kubeconfig core hands the runner holds exactly the
    disposable cluster's one context -- the fake kind wrote two, the learner-looking one is
    gone -- and is mode ``0o600`` (spec: 0600 in the attempt dir)."""
    handle = cluster.provision(attempt, tools=tools)

    assert handle.kubeconfig.is_file() and not handle.kubeconfig.is_symlink()
    assert stat.S_IMODE(handle.kubeconfig.stat().st_mode) == 0o600
    doc = yaml.safe_load(handle.kubeconfig.read_text(encoding="utf-8"))
    context = f"kind-{handle.name}"
    assert [item["name"] for item in doc["contexts"]] == [context]
    assert [item["name"] for item in doc["clusters"]] == [context]
    assert [item["name"] for item in doc["users"]] == [context]
    assert doc["current-context"] == context
    assert "learner-prod" not in handle.kubeconfig.read_text(encoding="utf-8")


def test_cluster_name_derives_from_the_attempt_id_only() -> None:
    """Brief item 2: ``studyloop-`` + the attempt id's prefix; nothing from the module."""
    assert cluster.cluster_name("1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d") == "studyloop-1a2b3c4d"
    assert cluster.cluster_name("ATTEMPT-0001").startswith("studyloop-")
    assert cluster.cluster_name("ATTEMPT-0001") == cluster.cluster_name("ATTEMPT-0001")
    with pytest.raises(ClusterError):
        cluster.cluster_name("---")


def test_provision_refuses_a_name_collision_without_creating(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 2/4: a cluster that already carries the derived name is a refusal, never a
    reuse; the listing is read-only and the only kind call made."""
    name = _expected_name(attempt)
    monkeypatch.setenv("FAKE_KIND_CLUSTERS", f"{name} studyloop-sentinel-abcd kind")

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    assert name in str(excinfo.value)
    assert excinfo.value.cluster == name
    assert fake_tools.calls() == [["get", "clusters"]]
    assert not (attempt.attempt_dir / "kubeconfig").exists()


def test_failed_create_without_a_kubeconfig_runs_no_delete(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec scenario "a failed create never deletes a cluster core cannot prove it made"
    (K0-review F1): kind failed BEFORE writing the attempt's kubeconfig, so core has no proof
    it created anything -- it re-lists read-only, finds the name absent, and reports the
    create failure alone. Zero ``delete`` argv in the log."""
    monkeypatch.setenv("FAKE_KIND_FAIL", "create")
    name = _expected_name(attempt)

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    message = str(excinfo.value)
    assert name in message and "create failed on purpose" in message
    assert excinfo.value.cluster == name
    assert [call[:2] for call in fake_tools.calls()] == [
        ["get", "clusters"],
        ["create", "cluster"],
        ["get", "clusters"],
    ], "no delete without proof; the second listing is the read-only re-check"
    assert "by hand" not in message, "nothing exists, so nothing to delete by hand"
    assert not (attempt.attempt_dir / "kubeconfig").exists()


def test_failed_create_that_left_an_unproven_cluster_reports_it_without_deleting(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K0-review F1, the dangerous half: the create failed without writing our kubeconfig but
    the name now appears in ``kind get clusters``. Core cannot prove that cluster is ours (the
    collision check and the create are two calls; something else may own the name), so it
    deletes NOTHING and tells the learner exactly what exists and how to delete it by hand."""
    monkeypatch.setenv("FAKE_KIND_FAIL", "create-registered")
    name = _expected_name(attempt)

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    message = str(excinfo.value)
    assert name in message
    assert "cannot prove it created" in message
    assert f"kind delete cluster --name {name} --kubeconfig" in message
    assert [call[:2] for call in fake_tools.calls()] == [
        ["get", "clusters"],
        ["create", "cluster"],
        ["get", "clusters"],
    ]


def test_failed_create_after_kind_wrote_the_kubeconfig_deletes_exactly_once(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K0-review F1, the provable half (the ``--wait`` timeout shape): kind wrote the
    attempt's own kubeconfig naming ``kind-<name>`` -- only our invocation could have written
    there -- then exited non-zero. That IS proof, so core issues exactly one delete and, the
    delete having succeeded, removes the kubeconfig."""
    monkeypatch.setenv("FAKE_KIND_FAIL", "create-after-write")
    name = _expected_name(attempt)

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    message = str(excinfo.value)
    assert name in message and "wait timed out" in message
    assert [call[:2] for call in fake_tools.calls()] == [
        ["get", "clusters"],
        ["create", "cluster"],
        ["delete", "cluster"],
    ]
    assert fake_tools.calls()[2][2:4] == ["--name", name]
    assert "deleted again" in message
    assert not (attempt.attempt_dir / "kubeconfig").exists()


def test_hung_create_is_killed_at_the_timeout_and_reported(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 1: a hard timeout. The fake writes the kubeconfig then sleeps 30 s (real kind
    writes it before ``--wait`` blocks); ``timeout_seconds=1`` stops it, the error says so and
    names the cluster, and -- the kubeconfig being proof -- the follow-up delete runs."""
    monkeypatch.setenv("FAKE_KIND_HANG", "create")
    started = time.monotonic()

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools, timeout_seconds=1)

    assert time.monotonic() - started < 15
    assert "timed out" in str(excinfo.value) and _expected_name(attempt) in str(excinfo.value)
    assert [call[:2] for call in fake_tools.calls()][-1] == ["delete", "cluster"]


def test_kind_never_sees_the_learners_kubeconfig_variable(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``KUBECONFIG`` in the learner's shell must not steer kind at the learner's own
    kubeconfig: core passes ``--kubeconfig`` explicitly AND drops the variable."""
    monkeypatch.setenv("KUBECONFIG", str(Path.home() / ".kube" / "config"))

    cluster.provision(attempt, tools=tools)

    seen = fake_tools.kind_env()
    assert seen and all("KUBECONFIG" not in env for env in seen)


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


def test_teardown_deletes_only_this_cluster_and_removes_the_kubeconfig(
    attempt: Attempt, tools: Mapping[str, Path], fake_tools: FakeTools, spawn_spy: list[SpawnCall]
) -> None:
    """Brief item 3: ``kind delete cluster --name <name>`` for the attempt's own cluster --
    plus ``--kubeconfig <ours>`` so kind edits our file, never the learner's default -- with
    the same spawn discipline; then the kubeconfig is removed. No listing, no prefix sweep."""
    handle = cluster.provision(attempt, tools=tools)
    before = len(fake_tools.calls())

    cluster.teardown(handle)

    calls = fake_tools.calls()
    assert calls[before:] == [
        ["delete", "cluster", "--name", handle.name, "--kubeconfig", str(handle.kubeconfig)]
    ]
    assert not handle.kubeconfig.exists()
    delete = _kind_spawns(spawn_spy, fake_tools)[-1]
    assert delete.args[0] == str(fake_tools.kind)
    assert delete.kwargs.get("shell", False) is False
    assert delete.kwargs.get("stdin") is subprocess.DEVNULL
    assert delete.kwargs.get("start_new_session") is True


def test_teardown_failure_is_an_error_naming_the_cluster(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 3 + K0-review F3: never silent -- the error names the cluster and the exact
    by-hand command INCLUDING ``--kubeconfig <attempt>/kubeconfig`` (so the learner never has to
    open their default kubeconfig), and the attempt's kubeconfig -- the only credential that
    can still reach the cluster -- is KEPT for that command."""
    handle = cluster.provision(attempt, tools=tools)
    monkeypatch.setenv("FAKE_KIND_FAIL", "delete")

    with pytest.raises(ClusterError) as excinfo:
        cluster.teardown(handle)

    message = str(excinfo.value)
    assert handle.name in message
    assert f"kind delete cluster --name {handle.name} --kubeconfig {handle.kubeconfig}" in message
    assert "delete failed on purpose" in message
    assert excinfo.value.cluster == handle.name
    assert handle.kubeconfig.is_file(), "the recovery credential must survive a failed delete"
    assert stat.S_IMODE(handle.kubeconfig.stat().st_mode) == 0o600


def test_failed_delete_after_a_provable_failed_create_keeps_the_kubeconfig(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K0-review F3 on the create-rollback path: kind wrote our kubeconfig (proof), the create
    then failed, and the follow-up delete fails too -- the kubeconfig stays and the message
    carries the exact command naming it."""
    monkeypatch.setenv("FAKE_KIND_FAIL", "create-after-write")
    monkeypatch.setenv("FAKE_KIND_FAIL_DELETE", "1")
    name = _expected_name(attempt)
    kubeconfig = attempt.attempt_dir / "kubeconfig"

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    message = str(excinfo.value)
    assert [call[:2] for call in fake_tools.calls()][-1] == ["delete", "cluster"]
    assert f"kind delete cluster --name {name} --kubeconfig {kubeconfig}" in message
    assert kubeconfig.is_file(), "a failed delete must not destroy the recovery credential"


@pytest.mark.parametrize(
    ("mode", "cause"),
    [
        pytest.param("misname", "expected exactly one context named", id="contexts-misnamed"),
        pytest.param("malformed", "not a list of mappings", id="contexts-not-mappings"),
    ],
)
def test_unusable_kubeconfig_after_a_successful_create_tears_down_and_names_the_cause(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    cause: str,
) -> None:
    """K0-review F4: kind exited 0 (so the cluster is provably ours) but wrote a kubeconfig the
    one-context rewrite cannot use -- contexts misnamed, or list entries that are not mappings
    (the ``AttributeError`` path the review found). Whatever the rewrite raises, exactly one
    delete runs and the error still names the cause and the cluster."""
    monkeypatch.setenv("FAKE_KIND_FAIL", mode)
    name = _expected_name(attempt)

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    message = str(excinfo.value)
    assert cause in message and name in message
    assert excinfo.value.cluster == name
    assert [call[:2] for call in fake_tools.calls()] == [
        ["get", "clusters"],
        ["create", "cluster"],
        ["delete", "cluster"],
    ]
    assert not (attempt.attempt_dir / "kubeconfig").exists()


def test_keyboard_interrupt_after_a_successful_create_tears_down_and_propagates(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K0-review F4: a Ctrl-C landing after kind created the cluster but before ``provision``
    returned (so before ``_drill`` has any handle to tear down) must delete the cluster on the
    way out -- and the ORIGINAL ``KeyboardInterrupt`` is what propagates, with the cluster
    named in its notes, not a swallowed or re-typed error."""
    real_rewrite = cluster.rewrite_kubeconfig

    def interrupted(path: Path, name: str) -> str:
        real_rewrite(path, name)
        raise KeyboardInterrupt

    monkeypatch.setattr(cluster, "rewrite_kubeconfig", interrupted)
    name = _expected_name(attempt)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        cluster.provision(attempt, tools=tools)

    assert any(name in note for note in getattr(excinfo.value, "__notes__", []))
    assert [call[:2] for call in fake_tools.calls()] == [
        ["get", "clusters"],
        ["create", "cluster"],
        ["delete", "cluster"],
    ]
    assert not (attempt.attempt_dir / "kubeconfig").exists()


def test_handle_for_rebuilds_the_handle_from_the_recorded_attempt(
    attempt: Attempt, tools: Mapping[str, Path], tmp_path: Path
) -> None:
    """``check``/``cleanup`` run in a later process: the handle comes from the attempt's id
    and its recorded kubeconfig, not from module text or a listing."""
    recorded = Attempt(
        attempt_id=attempt.attempt_id,
        drill=attempt.drill,
        snapshot_dir=attempt.snapshot_dir,
        attempt_dir=attempt.attempt_dir,
        target=TargetKind.KUBECONFIG_CONTEXT,
        kubeconfig=attempt.attempt_dir / "kubeconfig",
    )

    handle = cluster.handle_for(recorded, tools=tools)

    assert handle == cluster.ClusterHandle(
        name=_expected_name(attempt),
        kubeconfig=attempt.attempt_dir / "kubeconfig",
        kind=tools["kind"],
    )
    assert cluster.kubeconfig_path(attempt) == attempt.attempt_dir / "kubeconfig"
    assert os.path.isabs(handle.kubeconfig)


# ---------------------------------------------------------------------------
# `studyloop drill` end to end against the k8s-offline fixture (brief item 5)
# ---------------------------------------------------------------------------

K8S_FIXTURE = Path(__file__).parent / "fixtures" / "modules" / "k8s-offline"
K8S_MODULE_ID = "k8s-offline"
K8S_DRILL = f"{K8S_MODULE_ID}/cluster/current-context"


@pytest.fixture
def sessions_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    return db


@pytest.fixture
def installed_k8s(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: FakeTools
) -> DrillIdentity:
    """The fixture module copied to ``tmp_path`` (so a test may edit it) and 'installed'
    through the same locator seam ``test_module_drill_cli.py`` uses; attempts live under
    ``tmp_path`` too. Requires ``fake_tools`` so the scratch PATH is in force first."""
    snapshot = tmp_path / "snapshot"
    shutil.copytree(K8S_FIXTURE, snapshot)
    for script in (snapshot / "scripts").iterdir():
        script.chmod(0o755)
    monkeypatch.setattr(_drill, "attempts_root", lambda: tmp_path / "module-attempts")
    digest = _module_digest(snapshot)

    def locate(module_id: str) -> InstalledModule:
        if module_id != K8S_MODULE_ID:
            raise _drill.ModuleNotInstalledError(module_id)
        return InstalledModule(module_id=K8S_MODULE_ID, module_digest=digest, snapshot_dir=snapshot)

    monkeypatch.setattr(_drill, "locate_installed_module", locate)
    return DrillIdentity(
        module_id=K8S_MODULE_ID, module_digest=digest, deck_id="cluster", task_id="current-context"
    )


def _invoke(*args: str, confirm: str = "y") -> Any:
    return CliRunner().invoke(drill_group, list(args), input=f"{confirm}\n", catch_exceptions=False)


def _store() -> AttemptStore:
    return AttemptStore(root=_drill.attempts_root())


def _kinds(fake_tools: FakeTools) -> list[list[str]]:
    """Each fake-kind call reduced to its verb pair (``["get", "clusters"]`` ...)."""
    return [call[:2] for call in fake_tools.calls()]


def _set_phase_script(tmp_path: Path, name: str, body: str) -> None:
    script = tmp_path / "snapshot" / "scripts" / name
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)


def test_drill_setup_check_cleanup_run_against_the_disposable_cluster(
    installed_k8s: DrillIdentity,
    sessions_db: Path,
    fake_tools: FakeTools,
    spawn_spy: list[SpawnCall],
    tmp_path: Path,
) -> None:
    """Spec scenario "the drill's cluster is disposable": ``setup`` provisions BEFORE the
    consent prompt (which names the cluster and the kubeconfig), the attempt records the
    kubeconfig, every phase's child sees ``KUBECONFIG=<attempt>/kubeconfig`` naming only that
    cluster, ``check`` reuses it without touching kind, ``cleanup`` runs the module's script
    and THEN deletes exactly that cluster and closes the attempt."""
    store = _store()

    setup = _invoke("setup", K8S_DRILL)

    assert setup.exit_code == 0, setup.output
    attempt = store.current(installed_k8s)
    assert attempt is not None, "setup must leave the attempt open for check"
    name = f"studyloop-{attempt.attempt_id[:8]}"
    kubeconfig = cluster.kubeconfig_path(attempt)
    assert attempt.kubeconfig is not None and attempt.kubeconfig.resolve() == kubeconfig, (
        "the attempt record must carry the core-written kubeconfig for the later phases"
    )
    prompt, asked, _rest = setup.output.partition("Run this phase now?")
    assert asked, setup.output
    assert "Cluster:" in prompt and name in prompt, "the consent prompt names the cluster"
    assert f"Target:      kubeconfig-context {kubeconfig}" in prompt
    assert _kinds(fake_tools) == [["get", "clusters"], ["create", "cluster"]]
    assert f"setup KUBECONFIG={kubeconfig}" in setup.output
    assert f"setup context kind-{name}" in setup.output, "the child saw the one-context file"
    assert "setup passed (exit 0)" in setup.output

    check = _invoke("check", K8S_DRILL)

    assert check.exit_code == 0, check.output
    assert f"check context kind-{name}" in check.output
    assert "check passed (exit 0)" in check.output
    assert store.current(installed_k8s) == attempt, "check runs in the attempt setup opened"
    assert _kinds(fake_tools) == [["get", "clusters"], ["create", "cluster"]], (
        "check reuses the recorded kubeconfig; kind is not called"
    )

    cleanup = _invoke("cleanup", K8S_DRILL)

    assert cleanup.exit_code == 0, cleanup.output
    assert f"cleanup KUBECONFIG={kubeconfig}" in cleanup.output, "module cleanup ran first"
    assert "cleanup passed (exit 0)" in cleanup.output
    assert fake_tools.calls()[-1] == [
        "delete",
        "cluster",
        "--name",
        name,
        "--kubeconfig",
        str(kubeconfig),
    ]
    assert _kinds(fake_tools) == [["get", "clusters"], ["create", "cluster"], ["delete", "cluster"]]
    assert name in cleanup.output, "the learner is told the cluster is gone"
    assert store.current(installed_k8s) is None, "cleanup closes the attempt"
    assert not kubeconfig.exists()

    scripts_dir = (tmp_path / "snapshot" / "scripts").resolve()
    phase_spawns = [call for call in spawn_spy if Path(call.args[0]).parent == scripts_dir]
    assert [Path(call.args[0]).name for call in phase_spawns] == [
        "setup.sh",
        "check.sh",
        "cleanup.sh",
    ]
    for call in phase_spawns:
        assert call.kwargs["env"]["KUBECONFIG"] == str(kubeconfig)
    rows = _events(sessions_db)
    assert [row["phase"] for row in rows] == ["setup", "check", "cleanup"]
    assert {row["exit_class"] for row in rows} == {"passed"}


def test_declining_setup_consent_tears_down_the_cluster_it_had_created(
    installed_k8s: DrillIdentity, sessions_db: Path, fake_tools: FakeTools
) -> None:
    """Brief item 3: the cluster exists before the prompt (it is named in it), so ``n`` must
    delete it again and leave no open attempt."""
    result = _invoke("setup", K8S_DRILL, confirm="n")

    assert result.exit_code == 2, result.output
    assert "Not confirmed" in result.output
    assert _kinds(fake_tools) == [["get", "clusters"], ["create", "cluster"], ["delete", "cluster"]]
    assert _store().current(installed_k8s) is None
    assert _events(sessions_db) == []


def test_failed_setup_script_tears_down_the_cluster_and_does_not_start_the_attempt(
    installed_k8s: DrillIdentity, sessions_db: Path, fake_tools: FakeTools, tmp_path: Path
) -> None:
    """§5.5 *Exit codes* + brief item 3: setup non-zero = error, attempt not started -- and the
    cluster that was created for it is deleted."""
    _set_phase_script(tmp_path, "setup.sh", "#!/bin/sh\necho 'no nodes today' >&2\nexit 1\n")

    result = _invoke("setup", K8S_DRILL)

    assert result.exit_code == 2, result.output
    assert "setup failed (exit 1; error) -- attempt not started" in result.output
    assert _kinds(fake_tools)[-1] == ["delete", "cluster"]
    assert _store().current(installed_k8s) is None
    assert _events(sessions_db)[0]["exit_class"] == "error"


def test_check_timeout_tears_down_the_cluster_and_closes_the_attempt(
    installed_k8s: DrillIdentity, sessions_db: Path, fake_tools: FakeTools, tmp_path: Path
) -> None:
    """Brief item 3 names the check timeout as a failure path: the hung check is stopped, the
    phase is an error, and the attempt's cluster does not outlive it."""
    assert _invoke("setup", K8S_DRILL).exit_code == 0
    deck_path = tmp_path / "snapshot" / "decks" / "cluster.json"
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    deck["tasks"][0]["verification"]["timeoutSeconds"] = 1
    deck_path.write_text(json.dumps(deck), encoding="utf-8")
    _set_phase_script(tmp_path, "check.sh", "#!/bin/sh\nsleep 20\n")

    result = _invoke("check", K8S_DRILL)

    assert result.exit_code == 2, result.output
    assert "check timed out after 1s" in result.output
    assert _kinds(fake_tools)[-1] == ["delete", "cluster"]
    assert _store().current(installed_k8s) is None
    assert _events(sessions_db)[-1]["timed_out"] == 1


def test_check_exit_1_keeps_the_cluster_for_another_try(
    installed_k8s: DrillIdentity, sessions_db: Path, fake_tools: FakeTools, tmp_path: Path
) -> None:
    """``check`` exit 1 is "task not complete", the normal keep-trying loop -- not a failure
    path. The attempt stays open and kind is not called."""
    assert _invoke("setup", K8S_DRILL).exit_code == 0
    _set_phase_script(tmp_path, "check.sh", "#!/bin/sh\necho not yet\nexit 1\n")

    result = _invoke("check", K8S_DRILL)

    assert result.exit_code == 1, result.output
    assert "task not complete (exit 1)" in result.output
    assert _kinds(fake_tools) == [["get", "clusters"], ["create", "cluster"]]
    assert _store().current(installed_k8s) is not None


def test_teardown_failure_on_cleanup_is_an_error_naming_the_cluster(
    installed_k8s: DrillIdentity,
    sessions_db: Path,
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 3: a failed ``kind delete`` is reported as ERROR naming the cluster and the
    by-hand command -- never silently -- and the CLI exits non-zero even though the module's
    own cleanup passed; the attempt is still closed (a failed cleanup closes it, spec)."""
    assert _invoke("setup", K8S_DRILL).exit_code == 0
    attempt = _store().current(installed_k8s)
    assert attempt is not None
    name = f"studyloop-{attempt.attempt_id[:8]}"
    monkeypatch.setenv("FAKE_KIND_FAIL", "delete")

    result = _invoke("cleanup", K8S_DRILL)

    assert result.exit_code == 2, result.output
    assert "cleanup passed (exit 0)" in result.output, "the module's cleanup still ran"
    assert "ERROR" in result.output
    assert name in result.output
    kubeconfig = cluster.kubeconfig_path(attempt)
    assert f"kind delete cluster --name {name} --kubeconfig {kubeconfig}" in result.output
    assert _store().current(installed_k8s) is None
    assert kubeconfig.is_file(), "K0-review F3: the recovery credential survives a failed delete"


def test_missing_core_tool_refuses_before_consent_even_when_the_module_omits_it(
    installed_k8s: DrillIdentity, sessions_db: Path, fake_tools: FakeTools, tmp_path: Path
) -> None:
    """Brief item 6 / M1 Q2: ``kind``, ``kubectl`` and ``docker`` are CORE's prerequisites for
    this target kind, resolved up front whatever the module declares; an unresolvable one is
    an error naming the tool, before any consent and before kind is called."""
    manifest = tmp_path / "snapshot" / "module.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "prerequisites:\n  - id: kind\n  - id: kubectl\n  - id: docker\n",
            "prerequisites:\n  - id: kubectl\n",
        ),
        encoding="utf-8",
    )
    assert "id: docker" not in manifest.read_text(encoding="utf-8")
    (fake_tools.bin_dir / "docker").unlink()

    result = _invoke("setup", K8S_DRILL)

    assert result.exit_code == 1, result.output
    assert "'docker'" in result.output
    assert "Run this phase now?" not in result.output
    assert fake_tools.calls() == []
    assert _store().current(installed_k8s) is None


def test_check_without_an_open_attempt_is_refused_before_consent(
    installed_k8s: DrillIdentity, sessions_db: Path, fake_tools: FakeTools, tmp_path: Path
) -> None:
    """Only ``setup`` provisions (brief item 5); a ``check`` with nothing open on a
    kubeconfig-context drill has no cluster to run against, so it is refused up front naming
    ``drill setup`` -- not refused after consent by the runner's missing-kubeconfig branch.
    The attempt it opened is recorded and closed as refused (``test_module_lane_seams.py``
    pins that record), so nothing stays open."""
    result = _invoke("check", K8S_DRILL)

    assert result.exit_code == 1, result.output
    assert "drill setup" in result.output and "refusing to spawn" in result.output
    assert "Run this phase now?" not in result.output
    assert fake_tools.calls() == []
    assert _store().current(installed_k8s) is None
    records = list((tmp_path / "module-attempts").rglob("*.json"))
    assert len(records) == 1 and json.loads(records[0].read_text())["closed_at"] is not None


def test_name_collision_is_refused_before_consent_and_closes_the_attempt(
    installed_k8s: DrillIdentity,
    sessions_db: Path,
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 2 through the CLI: an existing cluster with the derived name is a refusal
    naming it, nothing is created, no consent is asked and no attempt stays open."""
    monkeypatch.setattr(cluster, "cluster_name", lambda attempt_id: "studyloop-fixed")
    monkeypatch.setenv("FAKE_KIND_CLUSTERS", "studyloop-sentinel-1234 studyloop-fixed")

    result = _invoke("setup", K8S_DRILL)

    assert result.exit_code == 1, result.output
    assert "studyloop-fixed" in result.output and "already exists" in result.output
    assert "Run this phase now?" not in result.output
    assert _kinds(fake_tools) == [["get", "clusters"]]
    assert _store().current(installed_k8s) is None


def test_keyboard_interrupt_right_after_provision_tears_down_the_cluster(
    installed_k8s: DrillIdentity,
    sessions_db: Path,
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K0-review F4 in ``_drill``: a Ctrl-C landing after ``cluster.provision`` returned but
    before the attempt record carries the kubeconfig (the window before the runner is even
    reached) must still delete the cluster and leave no open attempt. Injected where the
    record is written, i.e. immediately after a successful provision."""
    real_write = AttemptStore._write

    def interrupted(self: AttemptStore, path: Path, record: dict[str, Any]) -> None:
        if record.get("kubeconfig"):
            raise KeyboardInterrupt
        real_write(self, path, record)

    monkeypatch.setattr(AttemptStore, "_write", interrupted)

    result = CliRunner().invoke(drill_group, ["setup", K8S_DRILL], input="y\n")

    assert result.exit_code == 1, result.output
    assert "Aborted" in result.output
    assert _kinds(fake_tools) == [["get", "clusters"], ["create", "cluster"], ["delete", "cluster"]]
    assert "Run this phase now?" not in result.output


def test_keyboard_interrupt_during_a_phase_tears_down_the_cluster(
    installed_k8s: DrillIdentity,
    sessions_db: Path,
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 3: Ctrl-C after the cluster exists must not leave it running. Click turns
    the interrupt into ``Aborted!`` (exit 1); the delete and the close happen on the way out."""
    assert _invoke("setup", K8S_DRILL).exit_code == 0

    def interrupted(*_args: Any, **_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_phase", interrupted)

    result = CliRunner().invoke(drill_group, ["check", K8S_DRILL], input="y\n")

    assert result.exit_code == 1, result.output
    assert "Aborted" in result.output
    assert _kinds(fake_tools)[-1] == ["delete", "cluster"]
    assert _store().current(installed_k8s) is None
