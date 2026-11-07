from typing import Literal

from fastapi import APIRouter
from mistralai.client.models import ChatCompletionResponse
from pydantic import BaseModel, Field
from utils.mistral import caller_mistral_client

MODEL = "mistral-large-4"

router = APIRouter()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str


def _reply_text(completion: ChatCompletionResponse) -> str:
    content = completion.choices[0].message.content
    if isinstance(content, str):
        return content
    return "".join(chunk.text for chunk in content if getattr(chunk, "type", None) == "text")


@router.post(
    "",
    operation_id="chat_complete",
    summary="Send the conversation to Mistral and return the assistant's reply",
)
def chat(request: ChatRequest) -> ChatResponse:
    completion = caller_mistral_client().chat.complete(
        model=MODEL,
        messages=[message.model_dump() for message in request.messages],
    )
    return ChatResponse(reply=_reply_text(completion))
