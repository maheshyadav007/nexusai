from nexusai.contracts.onboarding import (
    FinishOnboarding,
    GetOnboarding,
    OnboardingChanged,
    OnboardingState,
    SetOnboardingStep,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context, Module

onboarding_module = Module(
    name="onboarding",
    migrations=[
        Migration(
            "onboarding_001",
            "CREATE TABLE onboarding ("
            " id INTEGER PRIMARY KEY CHECK (id = 1), step TEXT, completed INTEGER NOT NULL)",
        )
    ],
)


def _load(ctx: Context) -> OnboardingState:
    rows = ctx.bus.db.fetch_all("SELECT step, completed FROM onboarding")
    if not rows:
        return OnboardingState(completed=False)
    return OnboardingState(completed=bool(rows[0]["completed"]), current_step=rows[0]["step"])


def _save(ctx: Context, step: str | None, completed: bool) -> OnboardingState:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO onboarding (id, step, completed) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET step = excluded.step, completed = excluded.completed",
            (step, int(completed)),
        )
        work.emit(
            "onboarding.changed",
            OnboardingChanged(step=step, completed=completed).model_dump(),
            source=onboarding_module.name,
            trace_id=ctx.trace_id,
        )
    return _load(ctx)


@onboarding_module.query("onboarding.state")
def get_state(query: GetOnboarding, ctx: Context) -> OnboardingState:
    return _load(ctx)


@onboarding_module.command("onboarding.setStep")
def set_step(command: SetOnboardingStep, ctx: Context) -> OnboardingState:
    return _save(ctx, command.step, _load(ctx).completed)


@onboarding_module.command("onboarding.finish")
def finish(command: FinishOnboarding, ctx: Context) -> OnboardingState:
    return _save(ctx, None, True)
