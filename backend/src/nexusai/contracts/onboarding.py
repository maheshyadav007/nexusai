from pydantic import BaseModel, ConfigDict, Field


class GetOnboarding(BaseModel):
    pass


class OnboardingState(BaseModel):
    completed: bool
    current_step: str | None = None
    checklist_dismissed: bool = False


class SetOnboardingStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str = Field(pattern=r"^[a-z-]+$", max_length=32)


class FinishOnboarding(BaseModel):
    pass


class OnboardingChanged(BaseModel):
    step: str | None = None
    completed: bool


class DismissChecklist(BaseModel):
    model_config = ConfigDict(extra="forbid")
