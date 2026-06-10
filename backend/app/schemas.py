from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    objective: str = Field(..., min_length=3, max_length=2000)


class EnhanceRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=5000)


class PreviewRequest(BaseModel):
    message_template: str = Field(..., min_length=3, max_length=5000)
    limit: int = Field(default=5, ge=1, le=50)


class SendRequest(BaseModel):
    message_template: str = Field(..., min_length=3, max_length=5000)
    subject: str = Field(..., min_length=1, max_length=255)


class PromptQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=4000)
    max_emails: int = Field(default=0, ge=0)
    use_memory: bool = False
    history: list[dict[str, str]] = Field(default_factory=list)


class EmailActionRequest(BaseModel):
    action: str = Field(..., min_length=2, max_length=50)
    uid: str = Field(..., min_length=1, max_length=50)


class EmailBulkActionRequest(BaseModel):
    action: str = Field(..., min_length=2, max_length=50)
    uids: list[str] = Field(..., min_length=1)


class ChatTurnRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    role: str = Field(..., min_length=3, max_length=20)
    content: str = Field(..., min_length=1, max_length=12000)
