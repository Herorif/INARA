"""Typed conversations independent of microphone, audio session and UI lifetime."""

from services.capability_profiles import model_id, provider_key
import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from llm.base import Message, MessageRole
from services.tools import ServiceError


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(min_length=1, max_length=12_000)
    conversation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class ConversationResult(BaseModel):
    conversation_id: uuid.UUID
    request_id: uuid.UUID
    text: str
    status: Literal["succeeded"] = "succeeded"


@dataclass
class Conversation:
    owner: str
    project: str
    messages: list = field(default_factory=list)
    results: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def create_text_provider():
    # SDK and credentials are touched only on a request, never during server startup.
    key = provider_key()
    if not key:
        raise ServiceError(
            "provider_not_configured", "Set GEMINI_API_KEY in .env to enable AI text conversation."
        )
    from llm.gemini import GeminiProvider

    return GeminiProvider(api_key=key, model=model_id("text"))


class ConversationService:
    def __init__(self, dispatcher, provider_factory=create_text_provider, timeout=45, store=None):
        self.dispatcher = dispatcher
        self.provider_factory = provider_factory
        self.timeout = timeout
        self.conversations = {}
        self.store = store

    def restore(self, owner, conversation_id, project):
        key, path = str(conversation_id), str(project.resolve())
        if self.store is None:
            conversation = self.conversations.get(key)
            if conversation and (conversation.owner != owner or conversation.project != path):
                raise ServiceError(
                    "conversation_scope", "Start a new conversation for this project."
                )
            messages = conversation.messages if conversation else []
            return [
                {"role": message.role.value, "content": message.content} for message in messages
            ]
        self.store.migrate_history(key, owner, path, project / "chat_history.jsonl")
        return self.store.restore(key, owner, path)

    def release_owner(self, owner):
        # Preserve history on socket reconnect; ownership is the stable desktop client ID.
        self.dispatcher.disconnect(owner)

    async def reply(
        self, owner, request, project, request_approval=None, *, origin_sid=None, authorize=None
    ):
        if authorize:
            authorize()
        key = str(request.conversation_id)
        conversation = self.conversations.get(key)
        if conversation is None:
            if len(self.conversations) >= 128:
                raise ServiceError("conversation_limit", "Restart or start fewer conversations.")
            conversation = Conversation(owner, str(project.resolve()))
            self.conversations[key] = conversation
        if conversation.owner != owner or conversation.project != str(project.resolve()):
            raise ServiceError("conversation_scope", "Start a new conversation for this project.")
        async with conversation.lock:
            if authorize:
                authorize()
            request_id = str(request.request_id)
            if self.store is not None:
                history, previous = self.store.claim(
                    key, owner, conversation.project, request_id, request.text
                )
                if previous:
                    if previous["state"] == "failed":
                        raise ServiceError(previous["code"], previous["message"])
                    return ConversationResult.model_validate(previous["result"])
                conversation.messages = [
                    Message(MessageRole(item["role"]), item["content"]) for item in history
                ]
            elif request_id in conversation.results:
                previous_text, previous = conversation.results[request_id]
                if previous_text != request.text:
                    raise ServiceError("request_conflict", "This request ID was already used.")
                if isinstance(previous, ServiceError):
                    raise previous
                return previous
            provider = None
            messages = [*conversation.messages[-20:], Message(MessageRole.USER, request.text)]
            try:
                provider = self.provider_factory()
                for _ in range(5):
                    response = await asyncio.wait_for(
                        provider.generate(
                            messages,
                            tools=[{"function_declarations": self.dispatcher.schemas()}],
                            system_instruction=(
                                "You are INARA, a capable desktop assistant. Use project tools only "
                                "when needed. Tool access is enforced by the application. Report actual "
                                "results honestly. WhatsApp drafting and sending are unavailable. "
                                "No microphone or camera context is attached to this text conversation."
                            ),
                        ),
                        self.timeout,
                    )
                    if authorize:
                        authorize()
                    if not response.tool_calls:
                        if not response.text:
                            raise ServiceError("empty_response", "The provider returned no answer.")
                        result = ConversationResult(
                            conversation_id=request.conversation_id,
                            request_id=request.request_id,
                            text=response.text,
                        )
                        messages.append(Message(MessageRole.ASSISTANT, response.text))
                        # Store completed text turns only; signed tool content lives within this request.
                        conversation.messages = [
                            *conversation.messages,
                            Message(MessageRole.USER, request.text),
                            Message(MessageRole.ASSISTANT, response.text),
                        ][-20:]
                        if self.store is not None:
                            history = [
                                {"role": message.role.value, "content": message.content}
                                for message in conversation.messages
                            ]
                            self.store.finish(
                                key,
                                owner,
                                conversation.project,
                                request_id,
                                request.text,
                                {"state": "succeeded", "result": result.model_dump(mode="json")},
                                history,
                            )
                        conversation.results[request_id] = (request.text, result)
                        if len(conversation.results) > 64:
                            conversation.results.pop(next(iter(conversation.results)))
                        return result
                    attachments = []
                    candidates = getattr(response.raw, "candidates", None)
                    if candidates:
                        attachments = [
                            {"type": "provider_content", "content": candidates[0].content}
                        ]
                    messages.append(
                        Message(MessageRole.ASSISTANT, response.text or "", attachments=attachments)
                    )
                    for call in response.tool_calls:
                        try:
                            output = await self.dispatcher.dispatch(
                                owner,
                                call.name,
                                call.args,
                                {
                                    "project_path": project,
                                    "principal": owner,
                                    "origin_sid": origin_sid,
                                },
                                request_approval,
                                authorize=authorize,
                            )
                        except (ServiceError, ValidationError) as exc:
                            output = {
                                "error": getattr(exc, "code", "invalid_arguments"),
                                "message": str(exc)
                                if isinstance(exc, ServiceError)
                                else "Invalid tool arguments.",
                            }
                        messages.append(
                            Message(
                                MessageRole.TOOL,
                                json.dumps(output),
                                tool_call_id=call.id,
                                name=call.name,
                            )
                        )
                raise ServiceError("tool_limit", "The assistant reached its tool-step limit.")
            except ServiceError as exc:
                conversation.results[request_id] = (request.text, exc)
                raise
            except TimeoutError as exc:
                error = ServiceError("provider_timeout", "The AI request timed out. Try again.")
                conversation.results[request_id] = (request.text, error)
                raise error from exc
            except Exception as exc:
                # Do not expose SDK errors: they can contain credentials or private request data.
                error = ServiceError(
                    "provider_failed", "The AI provider could not complete this request."
                )
                conversation.results[request_id] = (request.text, error)
                raise error from exc
            finally:
                if provider is not None:
                    try:
                        await asyncio.wait_for(provider.close(), 5)
                    except Exception:
                        pass  # Cleanup failure must not discard a completed response.
                cached = conversation.results.get(request_id)
                if self.store is not None and cached and isinstance(cached[1], ServiceError):
                    error = cached[1]
                    self.store.finish(
                        key,
                        owner,
                        conversation.project,
                        request_id,
                        request.text,
                        {"state": "failed", "code": error.code, "message": str(error)},
                    )
                while len(conversation.results) > 64:
                    conversation.results.pop(next(iter(conversation.results)))
