"""studyctl eval — persona evaluation harness CLI commands."""

from __future__ import annotations

import platform
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import click
from rich.table import Table

from studyctl.agent_launcher import detect_agents
from studyctl.cli._shared import console
from studyctl.eval.git_ops import abort_if_dirty
from studyctl.eval.orchestrator import run_evaluation
from studyctl.eval.scenarios import builtin_scenarios_path, load_scenarios

# Repo root: packages/studyctl/src/studyctl/cli/_eval.py is 5 levels below repo root
_REPO_ROOT = Path(__file__).resolve().parents[5]

# ---------------------------------------------------------------------------
# Model tier recommendations
# ---------------------------------------------------------------------------

_MODEL_TIERS: list[tuple[float, bool | None, str, str]] = [
    # (min_gb, apple_silicon_required, model, note)
    (64.0, True, "gemma4:26b", ""),
    (64.0, False, "gemma4:26b", ""),
    (32.0, None, "gemma4:26b", ""),
    (16.0, None, "gemma4:26b", "tight fit — monitor VRAM pressure"),
    (8.0, None, "nemotron-3-nano:4b", ""),
]


def _recommended_model(ram_gb: float, apple_silicon: bool) -> tuple[str, str]:
    """Return (model_name, optional_note) for the given hardware."""
    for min_gb, apple_req, model, note in _MODEL_TIERS:
        if ram_gb >= min_gb and (apple_req is None or apple_req == apple_silicon):
            return model, note
    return "", "suggest OpenAI-compatible provider (RAM < 8 GB)"


# ---------------------------------------------------------------------------
# Hardware / Ollama helpers (isolated for mocking)
# ---------------------------------------------------------------------------


def _check_ollama_running() -> bool:
    """Return True if Ollama API is reachable at localhost:11434."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _detect_ram_gb() -> float:
    """Return total system RAM in GiB (best effort; returns 0.0 on failure)."""
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return int(result.stdout.strip()) / (1024**3)
        else:
            # Linux: read /proc/meminfo
            meminfo = Path("/proc/meminfo").read_text()
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024**2)
    except Exception:
        pass
    return 0.0


def _is_apple_silicon() -> bool:
    """Return True if running on Apple Silicon (arm64 macOS)."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _ollama_models() -> list[str]:
    """Return list of locally available Ollama model names."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return []
        # Skip header line; first column is the model name
        lines = result.stdout.strip().splitlines()
        models = []
        for line in lines[1:]:
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _eval_results_path() -> Path:
    """Return the path to eval-results.tsv in the project root."""
    return _REPO_ROOT / "eval-results.tsv"


# ---------------------------------------------------------------------------
# eval group + commands
# ---------------------------------------------------------------------------


@click.group(name="eval")
def eval_group() -> None:
    """Persona evaluation harness — score the study mentor against fixed scenarios."""


# ---- eval run ---------------------------------------------------------------


@eval_group.command()
@click.option(
    "--scenarios",
    "scenarios_arg",
    default="study",
    help="Scenario set name or path to YAML",
)
@click.option("--agent", default=None, help="Agent to evaluate (default: auto-detect)")
@click.option("--no-git-check", is_flag=True, help="Skip clean working tree check")
@click.pass_context
def run(ctx: click.Context, scenarios_arg: str, agent: str | None, no_git_check: bool) -> None:
    """Run evaluation scenarios against the current persona."""
    from studyctl.eval.judge.llm import LLMJudge
    from studyctl.eval.llm_client import LLMClient
    from studyctl.eval.reporter import TSVReporter
    from studyctl.eval.targets.persona import PersonaTarget
    from studyctl.settings import load_settings

    # 1. Git cleanliness check
    abort_if_dirty(allow_override=no_git_check)

    # 2. Load scenarios
    scenarios_path = builtin_scenarios_path() if scenarios_arg == "study" else Path(scenarios_arg)

    try:
        scenarios = load_scenarios(scenarios_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    # 3. Load eval config from settings
    settings = load_settings()
    judge_cfg = settings.eval.judge

    # 4. Create LLMClient from config
    import os

    api_key = os.environ.get(judge_cfg.api_key_env, "") if judge_cfg.api_key_env else ""
    llm_client = LLMClient(
        base_url=judge_cfg.base_url,
        model=judge_cfg.model,
        api_key=api_key,
        provider=judge_cfg.provider,
    )

    # 5. Create LLMJudge
    judge = LLMJudge(llm_client)

    # 6. Resolve agent
    if agent is None:
        available = detect_agents()
        if not available:
            raise click.ClickException(
                "No AI agent found. Install Claude Code, Gemini CLI, Kiro, or OpenCode.\n"
                "  Or specify one with: --agent <name>"
            )
        agent = available[0]

    # 7. Create PersonaTarget
    target = PersonaTarget(agent)

    # 8. Create TSVReporter
    reporter = TSVReporter(_eval_results_path())

    # 9. Run evaluation
    summary = run_evaluation(target, judge, scenarios, reporter, agent)

    # 10. Print summary table
    table = Table(title="Eval Results", show_lines=False)
    table.add_column("Scenario", style="cyan")
    table.add_column("Pass", justify="center")
    table.add_column("Score", justify="right")

    for result in summary.results:
        pass_icon = "[green]✓[/green]" if result.passed else "[red]✗[/red]"
        table.add_row(result.scenario_id, pass_icon, f"{result.weighted_score:.1f}%")

    console.print(table)

    passed_count = sum(1 for r in summary.results if r.passed)
    total_count = len(summary.results)
    console.print(
        f"\nAvg score: [bold]{summary.avg_score:.1f}%[/bold]  "
        f"Passed: [bold]{passed_count}/{total_count}[/bold]"
    )

    # 11. Write markdown report
    reports_dir = _REPO_ROOT / "docs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"eval-{summary.timestamp.replace(':', '-')}.md"
    report_file.write_text(reporter.generate_markdown(summary))
    console.print(f"[dim]Report written to {report_file.relative_to(_REPO_ROOT)}[/dim]")

    ctx.exit(0 if summary.all_passed else 1)


# ---- eval history -----------------------------------------------------------


@eval_group.command()
def history() -> None:
    """Show evaluation score history."""
    tsv_path = _eval_results_path()

    if not tsv_path.exists():
        console.print("No evaluation history yet.")
        console.print("[dim]Run 'studyctl eval run' to generate results.[/dim]")
        return

    import csv

    rows = []
    with tsv_path.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows.append(row)

    if not rows:
        console.print("No evaluation history yet.")
        return

    table = Table(title="Eval History", show_lines=False)
    table.add_column("Timestamp", style="dim")
    table.add_column("Agent", style="cyan")
    table.add_column("Scenario")
    table.add_column("Pass", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Commit", style="dim")

    for row in rows:
        heuristic = row.get("heuristic_pass", "False")
        passed = heuristic.lower() in ("true", "1", "yes")
        try:
            score = float(row.get("weighted_score", "0"))
            # A row is passing if heuristic passed AND score >= threshold
            from studyctl.eval.models import PASS_THRESHOLD

            passed = passed and score >= PASS_THRESHOLD
        except ValueError:
            score = 0.0

        pass_icon = "[green]✓[/green]" if passed else "[red]✗[/red]"
        table.add_row(
            row.get("timestamp", ""),
            row.get("agent", ""),
            row.get("scenario_id", ""),
            pass_icon,
            f"{score:.2f}",
            row.get("commit", ""),
        )

    console.print(table)


# ---- eval setup -------------------------------------------------------------


@eval_group.command()
def setup() -> None:
    """Detect hardware and recommend judge model configuration."""
    ollama_running = _check_ollama_running()
    ram_gb = _detect_ram_gb()
    apple_silicon = _is_apple_silicon()

    if ollama_running:
        console.print("[green]Ollama is running[/green] (localhost:11434)")
    else:
        console.print("[yellow]Ollama not running[/yellow] — start with: ollama serve")

    ram_display = f"{ram_gb:.0f}" if ram_gb > 0 else "unknown"
    chip_label = "Apple Silicon" if apple_silicon else "x86/ARM"
    console.print(f"RAM: [bold]{ram_display} GB[/bold]  Chip: [bold]{chip_label}[/bold]")

    recommended, note = _recommended_model(ram_gb, apple_silicon)

    if not recommended:
        console.print(
            "\n[yellow]RAM < 8 GB detected.[/yellow] "
            "Local LLM judging is not practical — suggest OpenAI-compatible provider."
        )
        console.print("\nAdd to your config.yaml:")
        console.print(
            "  eval:\n"
            "    judge:\n"
            "      provider: openai-compat\n"
            "      base_url: https://api.openai.com\n"
            "      model: gpt-4o-mini\n"
            "      api_key_env: OPENAI_API_KEY"
        )
        return

    if note:
        console.print(f"\n[yellow]Note:[/yellow] {note}")

    console.print(f"\nRecommended model: [bold]{recommended}[/bold]")

    if ollama_running:
        available_models = _ollama_models()
        if recommended in available_models:
            console.print(f"[green]{recommended} is already downloaded[/green]")
        else:
            console.print(
                f"[yellow]{recommended} not found locally.[/yellow] "
                f"Download with: ollama pull {recommended}"
            )

    console.print("\nAdd to your config.yaml:")
    console.print(
        f"  eval:\n"
        f"    judge:\n"
        f"      provider: ollama\n"
        f"      base_url: http://localhost:11434\n"
        f"      model: {recommended}"
    )
