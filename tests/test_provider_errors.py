"""Provider failures become actionable messages plus one safe diagnostic log line."""

import logging
import ssl

import httpx
import pytest
from google.genai import errors

from llm import claude, gemini
from llm.claude import ClaudeProvider
from llm.gemini import GeminiProvider
from services.conversation import ConversationRequest, ConversationService
from services.tools import ServiceError, ToolDispatcher, register_project_tools

USER_MARKER = "USER-TEXT-MARKER-7731"
SECRET_DETAIL = "provider-private-detail-4410"
ANTHROPIC_KEY = "sk-ant-api03-" + "x" * 40
GEMINI_KEY = "AQ.Ab8RN6" + "y" * 30
MODEL = "claude-sonnet-5-5"
GEMINI_MODEL = "gemini-3.8-flash"
GENERIC = "The AI provider could not complete this request."


# --- Anthropic --------------------------------------------------------------------


def anthropic_error(kind, status, message=SECRET_DETAIL, error_type=None, headers=None):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, headers=headers or {}, request=request)
    body = None
    if error_type:
        body = {"type": "error", "error": {"type": error_type, "message": message}}
    return getattr(anthropic, kind)(message, response=response, body=body)


def anthropic_connection(kind, cause=None):
    import anthropic
    import httpx2

    exc = getattr(anthropic, kind)(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    exc.__cause__ = cause
    return exc


CREDIT = "Your credit balance is too low to access the Anthropic API. " + SECRET_DETAIL
NO_CREDIT = (
    "Your Anthropic account is out of credit. Add credit under Billing in the Anthropic "
    "Console, then try again."
)

ANTHROPIC_CASES = [
    (lambda: anthropic_error("AuthenticationError", 401, error_type="authentication_error"),
     "provider_key_invalid",
     "Claude rejected your Anthropic key. Replace it in Preferences > AI.", "api_key_invalid"),
    (lambda: anthropic_error("PermissionDeniedError", 403, error_type="permission_error"),
     "provider_permission_denied",
     "Your Anthropic key isn't allowed to use Claude. Check the key in the Anthropic Console.",
     "permission_denied"),
    (lambda: anthropic_error("NotFoundError", 404, error_type="not_found_error"),
     "provider_model_not_found",
     f"Claude doesn't offer the model JARVIS asked for ({MODEL}).", "model_not_found"),
    (lambda: anthropic_error("BadRequestError", 400, CREDIT, "invalid_request_error"),
     "provider_no_credit", NO_CREDIT, "credit_balance"),
    # No body: the reason still comes from the message, case-insensitively.
    (lambda: anthropic_error("BadRequestError", 400, "CREDIT BALANCE too low"),
     "provider_no_credit", NO_CREDIT, "credit_balance"),
    (lambda: anthropic_error("BadRequestError", 400, error_type="invalid_request_error"),
     "provider_failed", GENERIC, None),
    (lambda: anthropic_error("RateLimitError", 429, error_type="rate_limit_error",
                             headers={"retry-after": "12"}),
     "provider_rate_limited", "Claude is limiting requests right now. Try again in 12 seconds.",
     "rate_limit"),
    (lambda: anthropic_error("InternalServerError", 500, error_type="api_error"),
     "provider_unavailable", "Claude is temporarily unavailable. Try again shortly.",
     "unavailable"),
    (lambda: anthropic_connection("APITimeoutError"),
     "provider_timeout", "The AI request timed out. Try again.", "timeout"),
    (lambda: anthropic_connection("APIConnectionError"),
     "provider_network", "Couldn't reach Claude. Check your internet connection.", "network"),
    (lambda: anthropic_connection("APIConnectionError", ssl.SSLError("CERTIFICATE_VERIFY_FAILED")),
     "provider_network",
     "Couldn't make a secure connection to Claude. A proxy or antivirus may be intercepting "
     "HTTPS.", "tls"),
]


@pytest.mark.parametrize("make, code, message, reason", ANTHROPIC_CASES)
def test_anthropic_errors_map_to_actionable_messages(make, code, message, reason):
    exc = make()
    error = claude.map_error(exc, MODEL)
    assert (error.code, str(error)) == (code, message)
    assert claude.diagnose(exc)[2] == reason


def test_anthropic_model_not_found_without_a_model_id():
    error = claude.map_error(anthropic_error("NotFoundError", 404))
    assert str(error) == "Claude doesn't offer the model JARVIS asked for."


def test_anthropic_unknown_exception_is_generic():
    error = claude.map_error(RuntimeError(SECRET_DETAIL), MODEL)
    assert (error.code, str(error)) == ("provider_failed", GENERIC)


# --- Gemini -----------------------------------------------------------------------


def client_error(code, status, message=SECRET_DETAIL, cls=errors.ClientError, details=None):
    error = {"code": code, "status": status, "message": message}
    if details:
        error["details"] = details
    return cls(code, {"error": error})


KEY = "Google rejected your Gemini key. Replace it in Preferences > AI."
REGION = "Gemini isn't available in your region with this key."
UNAVAILABLE = "Gemini is temporarily unavailable. Try again shortly."
GEMINI_CASES = [
    (lambda: client_error(401, "UNAUTHENTICATED"), "provider_key_invalid", KEY,
     "api_key_invalid"),
    (lambda: client_error(403, "PERMISSION_DENIED"), "provider_key_invalid", KEY,
     "api_key_invalid"),
    (lambda: client_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid "
                          "API key."), "provider_key_invalid", KEY, "api_key_invalid"),
    (lambda: client_error(400, "INVALID_ARGUMENT", details=[{"reason": "API_KEY_INVALID"}]),
     "provider_key_invalid", KEY, "api_key_invalid"),
    (lambda: client_error(400, "ACCESS_TOKEN_TYPE_UNSUPPORTED"), "provider_key_invalid", KEY,
     "api_key_invalid"),
    (lambda: client_error(400, "FAILED_PRECONDITION",
                          "User location is not supported for the API use."),
     "provider_region", REGION, "region"),
    (lambda: client_error(400, "INVALID_ARGUMENT", "This region is not supported."),
     "provider_region", REGION, "region"),
    (lambda: client_error(404, "NOT_FOUND"), "provider_model_not_found",
     f"Gemini doesn't offer the model JARVIS asked for ({GEMINI_MODEL}).", "model_not_found"),
    (lambda: client_error(429, "RESOURCE_EXHAUSTED"), "provider_rate_limited",
     "Gemini's quota or rate limit is used up. Try again later, or check your plan in Google "
     "AI Studio.", "quota"),
    (lambda: client_error(503, "UNAVAILABLE", cls=errors.ServerError), "provider_unavailable",
     UNAVAILABLE, "unavailable"),
    (lambda: client_error(500, "INTERNAL", cls=errors.ServerError), "provider_unavailable",
     UNAVAILABLE, "unavailable"),
    (lambda: httpx.ConnectError("down"), "provider_network",
     "Couldn't reach Gemini. Check your internet connection.", "network"),
    (lambda: httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] bad cert"), "provider_network",
     "Couldn't make a secure connection to Gemini. A proxy or antivirus may be intercepting "
     "HTTPS.", "tls"),
    (lambda: httpx.ReadTimeout("slow"), "provider_timeout",
     "The AI request timed out. Try again.", "timeout"),
    (lambda: client_error(400, "INVALID_ARGUMENT"), "provider_failed", GENERIC, None),
    (lambda: RuntimeError(SECRET_DETAIL), "provider_failed", GENERIC, None),
]


@pytest.mark.parametrize("make, code, message, reason", GEMINI_CASES)
def test_gemini_errors_map_to_actionable_messages(make, code, message, reason):
    exc = make()
    error = gemini.map_error(exc, GEMINI_MODEL)
    assert (error.code, str(error)) == (code, message)
    assert gemini.diagnose(exc)[2] == reason


# --- end to end through the conversation, with the log line ------------------------


class RaisingStream:
    def __init__(self, exc):
        self.exc = exc

    async def __aenter__(self):
        raise self.exc

    async def __aexit__(self, *args):
        return False


class AnthropicClient:
    def __init__(self, exc):
        self.exc = exc
        self.beta = self
        self.messages = self

    def stream(self, **params):
        return RaisingStream(self.exc)

    async def close(self):
        pass


class GeminiClient:
    def __init__(self, exc):
        self.exc = exc
        self.aio = self
        self.models = self

    async def generate_content(self, **kwargs):
        raise self.exc

    async def aclose(self):
        pass


def conversation(provider):
    dispatcher = ToolDispatcher(lambda: {"read_file": False, "write_file": False})
    register_project_tools(dispatcher)
    return ConversationService(dispatcher, lambda: provider)


def claude_provider(exc):
    return ClaudeProvider(api_key=ANTHROPIC_KEY, model=MODEL, client=AnthropicClient(exc))


def gemini_provider(exc):
    provider = GeminiProvider(api_key=GEMINI_KEY, model=GEMINI_MODEL)
    provider._GeminiProvider__client = GeminiClient(exc)
    return provider


def failure_lines(caplog):
    return [
        record.getMessage() for record in caplog.records
        if "AI provider request failed" in record.getMessage()
    ]


@pytest.mark.parametrize(
    "provider, expected, code",
    [
        (lambda: claude_provider(anthropic_error("BadRequestError", 400, CREDIT,
                                                 "invalid_request_error")),
         "provider=claude error=BadRequestError status=400 kind=invalid_request_error "
         "reason=credit_balance", "provider_no_credit"),
        (lambda: claude_provider(anthropic_error("NotFoundError", 404,
                                                 error_type="not_found_error")),
         "provider=claude error=NotFoundError status=404 kind=not_found_error "
         "reason=model_not_found", "provider_model_not_found"),
        (lambda: claude_provider(anthropic_error("BadRequestError", 400,
                                                 error_type="invalid_request_error")),
         "provider=claude error=BadRequestError status=400 kind=invalid_request_error reason=-",
         "provider_failed"),
        (lambda: claude_provider(RuntimeError(SECRET_DETAIL + ANTHROPIC_KEY)),
         "provider=claude error=RuntimeError status=- kind=- reason=-", "provider_failed"),
        (lambda: gemini_provider(client_error(400, "INVALID_ARGUMENT",
                                              "API key not valid. " + GEMINI_KEY)),
         "provider=gemini error=ClientError status=400 kind=INVALID_ARGUMENT "
         "reason=api_key_invalid", "provider_key_invalid"),
        (lambda: gemini_provider(client_error(429, "RESOURCE_EXHAUSTED")),
         "provider=gemini error=ClientError status=429 kind=RESOURCE_EXHAUSTED reason=quota",
         "provider_rate_limited"),
        (lambda: gemini_provider(RuntimeError(SECRET_DETAIL + GEMINI_KEY)),
         "provider=gemini error=RuntimeError status=- kind=- reason=-", "provider_failed"),
    ],
)
@pytest.mark.asyncio
async def test_failed_requests_log_one_safe_line(tmp_path, caplog, provider, expected, code):
    caplog.set_level(logging.WARNING)
    service = conversation(provider())
    with pytest.raises(ServiceError) as raised:
        await service.reply("owner", ConversationRequest(text=USER_MARKER), tmp_path)
    assert raised.value.code == code
    (line,) = failure_lines(caplog)
    assert line == "AI provider request failed: " + expected
    logged = caplog.text
    for forbidden in (USER_MARKER, SECRET_DETAIL, "credit balance", "API key not valid",
                      ANTHROPIC_KEY, GEMINI_KEY, "sk-ant", "AQ."):
        assert forbidden not in logged
        assert forbidden not in str(raised.value)


def test_log_fields_never_carry_free_text(caplog):
    from llm.base import log_provider_failure

    caplog.set_level(logging.WARNING)
    log_provider_failure("claude", RuntimeError(), 400, "has spaces " + SECRET_DETAIL, "x y")
    (line,) = failure_lines(caplog)
    assert line.endswith("status=400 kind=- reason=-") and SECRET_DETAIL not in line


# --- Gemini tool declarations use standard JSON Schema -------------------------------


class RecordingGeminiClient:
    def __init__(self):
        self.aio = self
        self.models = self
        self.configs = []

    async def generate_content(self, **kwargs):
        self.configs.append(kwargs["config"])
        from types import SimpleNamespace

        return SimpleNamespace(candidates=[])

    async def generate_content_stream(self, **kwargs):
        self.configs.append(kwargs["config"])

        async def chunks():
            return
            yield

        return chunks()

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_gemini_sends_real_tool_schemas_as_parameters_json_schema(application_factory):
    import copy

    from google.genai import types

    from llm.base import Message, MessageRole

    schemas = application_factory().dispatcher.schemas()
    assert schemas
    original = copy.deepcopy(schemas)
    provider = GeminiProvider(api_key=GEMINI_KEY, model=GEMINI_MODEL)
    client = RecordingGeminiClient()
    provider._GeminiProvider__client = client
    messages = [Message(MessageRole.USER, "hi")]
    tools = [{"function_declarations": schemas}]
    await provider.generate(messages, tools=tools)
    async for _ in provider.stream(messages, tools=tools):
        pass
    assert len(client.configs) == 2
    for config in client.configs:
        (tool,) = config.tools
        declarations = tool["function_declarations"]
        assert len(declarations) == len(original)
        for sent, schema in zip(declarations, original, strict=True):
            assert "parameters" not in sent
            assert sent["parameters_json_schema"] == schema["parameters"]
            assert {k: v for k, v in sent.items() if k != "parameters_json_schema"} == {
                k: v for k, v in schema.items() if k != "parameters"
            }
        # The SDK accepts the adapted shape as a Tool.
        parsed = types.Tool.model_validate(tool)
        assert all(d.parameters is None and d.parameters_json_schema
                   for d in parsed.function_declarations)
    assert schemas == original  # the dispatcher's own schemas are not mutated


def test_gemini_tools_leaves_sdk_objects_alone():
    from google.genai import types

    from llm.gemini import gemini_tools

    sdk_tool = types.Tool(function_declarations=[types.FunctionDeclaration(name="x")])
    already = {"function_declarations": [{"name": "y", "parameters_json_schema": {}}]}
    assert gemini_tools([sdk_tool, already]) == [sdk_tool, already]
    assert gemini_tools([sdk_tool])[0] is sdk_tool
