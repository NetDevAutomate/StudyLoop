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
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from test_module_runner import SpawnCall, spawn_spy

from studyloop.modules import cluster, runner
from studyloop.modules.attempt import Attempt, AttemptStore, DrillIdentity, TargetKind
from studyloop.modules.cluster import ClusterError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["spawn_spy"]  # re-exported pytest fixture from test_module_runner

FAKE_KIND = textwrap.dedent(
    """\
    #!/bin/sh
    # Fake kind for the offline K0 tests. Records argv; never touches Docker.
    set -u
    log="${FAKE_KIND_LOG:?FAKE_KIND_LOG must be set}"
    { for arg in "$@"; do printf '%s\\t' "$arg"; done; printf '\\n'; } >> "$log"
    printf 'KUBECONFIG=%s\\n' "${KUBECONFIG:-<unset>}" >> "$log.env"
    case "${1:-} ${2:-}" in
      "get clusters")
        if [ -n "${FAKE_KIND_CLUSTERS:-}" ]; then
          for name in $FAKE_KIND_CLUSTERS; do printf '%s\\n' "$name"; done
        else
          echo "No kind clusters found." >&2
        fi
        exit 0 ;;
      "create cluster")
        if [ "${FAKE_KIND_HANG:-}" = create ]; then sleep 30; fi
        if [ "${FAKE_KIND_FAIL:-}" = create ]; then
          echo "fake kind: create failed on purpose" >&2
          exit 1
        fi
        name=""; kubeconfig=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --name) name="$2"; shift ;;
            --kubeconfig) kubeconfig="$2"; shift ;;
          esac
          shift
        done
        cat > "$kubeconfig" <<EOF
    apiVersion: v1
    kind: Config
    preferences: {}
    clusters:
    - name: kind-$name
      cluster: {server: 'https://127.0.0.1:6443'}
    - name: learner-prod
      cluster: {server: 'https://learner.example:6443'}
    contexts:
    - name: kind-$name
      context: {cluster: kind-$name, user: kind-$name}
    - name: learner-prod
      context: {cluster: learner-prod, user: learner-admin}
    current-context: kind-$name
    users:
    - name: kind-$name
      user: {username: kind-$name}
    - name: learner-admin
      user: {username: learner-admin}
    EOF
        echo "Creating cluster \\"$name\\" ... (fake)"
        exit 0 ;;
      "delete cluster")
        if [ "${FAKE_KIND_FAIL:-}" = delete ]; then
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

    def kind_env(self) -> list[str]:
        """``KUBECONFIG=...`` as the fake kind saw it, one entry per invocation."""
        env_log = Path(f"{self.log}.env")
        return env_log.read_text(encoding="utf-8").splitlines() if env_log.exists() else []

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
    for var in ("FAKE_KIND_FAIL", "FAKE_KIND_HANG", "FAKE_KIND_CLUSTERS", "KUBECONFIG"):
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


def test_failed_create_names_the_cluster_and_deletes_what_kind_may_have_left(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero ``kind create`` is a :class:`ClusterError` carrying kind's stderr and the
    cluster name; because the name was free a moment ago, anything now carrying it is ours,
    so core issues one ``delete`` for it rather than leave a half-made cluster behind."""
    monkeypatch.setenv("FAKE_KIND_FAIL", "create")
    name = _expected_name(attempt)

    with pytest.raises(ClusterError) as excinfo:
        cluster.provision(attempt, tools=tools)

    message = str(excinfo.value)
    assert name in message and "create failed on purpose" in message
    assert [call[:2] for call in fake_tools.calls()] == [
        ["get", "clusters"],
        ["create", "cluster"],
        ["delete", "cluster"],
    ]
    assert fake_tools.calls()[2][2:4] == ["--name", name]


def test_hung_create_is_killed_at_the_timeout_and_reported(
    attempt: Attempt,
    tools: Mapping[str, Path],
    fake_tools: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief item 1: a hard timeout. The fake sleeps 30 s; ``timeout_seconds=1`` stops it,
    the error says so and names the cluster, and the follow-up delete still runs."""
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

    assert fake_tools.kind_env() and all(
        line == "KUBECONFIG=<unset>" for line in fake_tools.kind_env()
    )


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
    """Brief item 3: never silent -- the error names the cluster and the by-hand command so
    the learner can delete it; the kubeconfig is still removed."""
    handle = cluster.provision(attempt, tools=tools)
    monkeypatch.setenv("FAKE_KIND_FAIL", "delete")

    with pytest.raises(ClusterError) as excinfo:
        cluster.teardown(handle)

    message = str(excinfo.value)
    assert handle.name in message
    assert f"kind delete cluster --name {handle.name}" in message
    assert "delete failed on purpose" in message
    assert excinfo.value.cluster == handle.name
    assert not handle.kubeconfig.exists()


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
