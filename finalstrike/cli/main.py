"""FinalStrike Typer CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console

from finalstrike import __version__
from finalstrike.config.context import load_repo_context
from finalstrike.config.plan import load_verification_plan
from finalstrike.config.loader import format_validation_error, load_config
from finalstrike.config.models import LayerStatus
from finalstrike.env.orchestrator import EnvOrchestrator
from finalstrike.doctor import CheckStatus, doctor_exit_code, run_doctor_checks
from finalstrike.orchestrator.run import execute_run, format_run_result_json, parse_layers

app = typer.Typer(
    name="finalstrike",
    help="Cursor cloud agent testing mirror — orchestrator and evidence recorder.",
    no_args_is_help=True,
)
env_app = typer.Typer(help="Manage target repo environment (install, terminals).")
app.add_typer(env_app, name="env")
console = Console(stderr=True)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"finalstrike {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-V",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
) -> None:
    """FinalStrike CLI."""


_STATUS_STYLE = {
    CheckStatus.OK: "green",
    CheckStatus.WARN: "yellow",
    CheckStatus.FAIL: "red",
    CheckStatus.SKIP: "dim",
}

_STATUS_LABEL = {
    CheckStatus.OK: "ok",
    CheckStatus.WARN: "warn",
    CheckStatus.FAIL: "fail",
    CheckStatus.SKIP: "skip",
}


@app.command("doctor")
def doctor(
    repo: Annotated[
        Optional[Path],
        typer.Option(
            "--repo",
            "-r",
            help="Fixture repo for capabilities and secrets checks.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Pre-flight checks for secrets, PATH, fixture gaps, and P5+ dependencies."""
    from rich.table import Table

    checks = run_doctor_checks(repo=repo)
    table = Table(title="FinalStrike doctor", show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    for check in checks:
        style = _STATUS_STYLE[check.status]
        label = _STATUS_LABEL[check.status]
        table.add_row(check.name, f"[{style}]{label}[/{style}]", check.detail)

    console.print(table)
    console.print(
        "\nSee docs/PHASE_GAPS.md for gap registry and per-phase pre-flight steps."
    )
    raise typer.Exit(code=doctor_exit_code(checks))


@app.command("validate-config")
def validate_config(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo",
            "-r",
            help="Path to the target repository containing finalstrike.yaml.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
) -> None:
    """Load and validate finalstrike.yaml from a target repo."""
    if not repo.exists():
        console.print(f"[red]Error:[/red] Repo path does not exist: {repo}")
        raise typer.Exit(code=1)

    try:
        config = load_config(repo)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except NotADirectoryError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML parse error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        console.print(f"[red]{format_validation_error(exc)}[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]✓[/green] Configuration valid for project "
        f"[bold]{config.project.name}[/bold] "
        f"(finalstrike.yaml v{config.version})"
    )


@app.command("plan")
def plan(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo",
            "-r",
            help="Path to the target repository containing finalstrike.yaml.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    acceptance: Annotated[
        Optional[Path],
        typer.Option(
            "--acceptance",
            "-a",
            help="Path to acceptance criteria markdown file.",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    acceptance_stdin: Annotated[
        bool,
        typer.Option(
            "--acceptance-stdin",
            help="Read acceptance criteria from stdin.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Print merged context without calling the LLM planner.",
        ),
    ] = True,
) -> None:
    """Load repo context and acceptance criteria; print merged plan context."""
    if not repo.exists():
        console.print(f"[red]Error:[/red] Repo path does not exist: {repo}")
        raise typer.Exit(code=1)

    if acceptance is not None and acceptance_stdin:
        console.print(
            "[red]Error:[/red] Use only one of --acceptance or --acceptance-stdin."
        )
        raise typer.Exit(code=1)

    if acceptance is None and not acceptance_stdin:
        console.print(
            "[red]Error:[/red] Provide --acceptance FILE or --acceptance-stdin."
        )
        raise typer.Exit(code=1)

    try:
        context = load_repo_context(
            repo,
            acceptance_path=acceptance,
            acceptance_stdin=acceptance_stdin,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except NotADirectoryError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML parse error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        console.print(f"[red]{format_validation_error(exc)}[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if dry_run:
        typer.echo(context.format_dry_run())
        return

    console.print(
        "[yellow]Note:[/yellow] LLM planner is not implemented yet; "
        "showing merged context."
    )
    typer.echo(context.format_dry_run())


def _load_context_or_exit(
    repo: Path,
    *,
    acceptance: Path | None = None,
    acceptance_stdin: bool = False,
    require_acceptance: bool = False,
):
    if not repo.exists():
        console.print(f"[red]Error:[/red] Repo path does not exist: {repo}")
        raise typer.Exit(code=1)

    if require_acceptance:
        if acceptance is not None and acceptance_stdin:
            console.print(
                "[red]Error:[/red] Use only one of --acceptance or --acceptance-stdin."
            )
            raise typer.Exit(code=1)
        if acceptance is None and not acceptance_stdin:
            console.print(
                "[red]Error:[/red] Provide --acceptance FILE or --acceptance-stdin."
            )
            raise typer.Exit(code=1)

    try:
        return load_repo_context(
            repo,
            acceptance_path=acceptance,
            acceptance_stdin=acceptance_stdin,
            inject_secrets=True,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except NotADirectoryError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except yaml.YAMLError as exc:
        console.print(f"[red]YAML parse error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        console.print(f"[red]{format_validation_error(exc)}[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@env_app.command("up")
def env_up(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo",
            "-r",
            help="Path to the target repository.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    health_timeout: Annotated[
        float,
        typer.Option(
            "--health-timeout",
            help="Seconds to wait for API health checks.",
        ),
    ] = 60.0,
) -> None:
    """Install deps, start terminals, and wait for health checks."""
    context = _load_context_or_exit(repo)
    orchestrator = EnvOrchestrator(
        repo=context.repo,
        environment=context.environment,
        config=context.config,
        subprocess_env=context.subprocess_env,
        health_timeout=health_timeout,
    )
    result = orchestrator.up()
    if result.status == LayerStatus.SKIPPED:
        console.print("[yellow]Environment bootstrap skipped[/yellow] (no environment.json).")
        raise typer.Exit(code=0)
    if result.status == LayerStatus.FAILED:
        console.print("[red]Environment bootstrap failed[/red]")
        if result.logs:
            console.print(result.logs)
        raise typer.Exit(code=1)

    console.print(
        f"[green]✓[/green] Environment ready "
        f"({result.duration_ms}ms, processes running — use `finalstrike env down` to stop)"
    )


@env_app.command("down")
def env_down(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo",
            "-r",
            help="Path to the target repository.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
) -> None:
    """Stop background terminals started by `env up`."""
    context = _load_context_or_exit(repo)
    orchestrator = EnvOrchestrator(
        repo=context.repo,
        environment=context.environment,
        config=context.config,
        subprocess_env=context.subprocess_env,
    )
    messages = orchestrator.down()
    if messages:
        for message in messages:
            console.print(message)
    else:
        console.print("No running environment processes found.")
    console.print("[green]✓[/green] Environment stopped.")


@app.command("run")
def run(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo",
            "-r",
            help="Path to the target repository containing finalstrike.yaml.",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    acceptance: Annotated[
        Optional[Path],
        typer.Option(
            "--acceptance",
            "-a",
            help="Path to acceptance criteria markdown file.",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    acceptance_stdin: Annotated[
        bool,
        typer.Option(
            "--acceptance-stdin",
            help="Read acceptance criteria from stdin.",
        ),
    ] = False,
    layers: Annotated[
        Optional[str],
        typer.Option(
            "--layers",
            help="Comma-separated layers to run: env,build,terminal,api.",
        ),
    ] = None,
    plan: Annotated[
        Optional[Path],
        typer.Option(
            "--plan",
            "-p",
            help="Path to VerificationPlan JSON (optional API checks beyond yaml health).",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    branch: Annotated[
        Optional[str],
        typer.Option(
            "--branch",
            help="Branch name for report metadata only (no git checkout).",
        ),
    ] = None,
    health_timeout: Annotated[
        float,
        typer.Option(
            "--health-timeout",
            help="Seconds to wait for API health checks when env layer runs.",
        ),
    ] = 60.0,
) -> None:
    """Execute verification layers and emit RunResult JSON."""
    context = _load_context_or_exit(
        repo,
        acceptance=acceptance,
        acceptance_stdin=acceptance_stdin,
        require_acceptance=True,
    )
    try:
        selected_layers = parse_layers(layers)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    verification_plan = None
    if plan is not None:
        try:
            verification_plan = load_verification_plan(plan)
        except FileNotFoundError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    result = execute_run(
        context,
        layers=selected_layers,
        branch=branch,
        health_timeout=health_timeout,
        plan=verification_plan,
    )
    typer.echo(format_run_result_json(result))
    if result.status.value == "failed":
        raise typer.Exit(code=1)
