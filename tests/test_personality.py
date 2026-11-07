"""Classic JARVIS personality (P0): the persona text and the owner's form of address."""

import re

import pytest
from pydantic import ValidationError

from services.conversation import ADDRESS_LINES, PERSONA, PHONE_LIMITS, persona
from services.live_config import VOICE_LINE
from services.settings import ASSISTANT_DEFAULTS, SettingsPatch, SettingsService, SettingsStore

EXPECTED_PERSONA = (
    "You are JARVIS, the owner's personal assistant on this Windows PC, with the manner of a "
    "seasoned butler and the mind of an engineer: composed, precise and quietly witty. Lead with "
    "the answer, then only the detail that matters, and keep it brief. A dry, understated remark "
    "is welcome now and then, never at the owner's expense and never when something has gone "
    "wrong. No filler, no exclamation marks, no emoji. Think a step ahead: when an obvious next "
    "step would help, offer it in one short question, such as 'Shall I set a reminder?'. You act "
    "on this PC only through the tools provided. Know what they can do and use them: never say "
    "you can't do something a tool can do, and be plain about what isn't possible yet. Many "
    "actions need the owner's approval: say in one line what you are about to do before doing "
    "it, and never claim something is done unless a tool result confirms it. If a request is "
    "ambiguous or risky, ask one short question. The owner is in Malaysia (Asia/Kuala_Lumpur) "
    "and may write in English or Malay; reply in the language they use."
)
SIR = " Address the owner as 'sir' (in Malay, 'tuan'), naturally and not in every sentence."
MAAM = " Address the owner as 'ma'am' (in Malay, 'puan'), naturally and not in every sentence."
NONE = " Don't use a form of address."
NAMED = " The owner's name is Hiro Tan; use it sparingly."
BY_NAME = (
    " The owner's name is Hiro Tan; address them by name, naturally and not in every sentence."
)


def settings(address=None, name=None):
    assistant = {}
    if address is not None:
        assistant["address"] = address
    if name is not None:
        assistant["owner_name"] = name
    return {"assistant": assistant}


def test_persona_is_the_classic_jarvis_text():
    assert PERSONA == EXPECTED_PERSONA
    assert ADDRESS_LINES == {"sir": SIR, "maam": MAAM, "none": NONE}


@pytest.mark.parametrize(
    ("address", "name", "expected"),
    [
        ("sir", None, SIR),
        ("sir", "Hiro Tan", NAMED + SIR),
        ("maam", None, MAAM),
        ("maam", "Hiro Tan", NAMED + MAAM),
        ("name", None, ""),
        ("name", "", ""),
        ("name", "   ", ""),
        ("name", "Hiro Tan", BY_NAME),
        ("none", None, NONE),
        ("none", "Hiro Tan", NAMED + NONE),
    ],
)
def test_address_sentence_for_every_mode(address, name, expected):
    assert persona(settings(address, name)) == PERSONA + expected
    assert persona(settings(address, name), PHONE_LIMITS) == PERSONA + expected + " " + PHONE_LIMITS
    # Byte-stable for a given setting.
    assert persona(settings(address, name), VOICE_LINE) == persona(
        settings(address, name), VOICE_LINE
    )


def test_old_settings_without_address_read_as_sir():
    assert persona({}) == PERSONA + SIR
    assert persona(None) == PERSONA + SIR
    assert (
        persona({"assistant": {"brain": "auto", "owner_name": "Hiro Tan"}}) == PERSONA + NAMED + SIR
    )
    # A hand-edited or stale value falls back to the default rather than breaking the prompt.
    assert persona(settings("butler", "Hiro Tan")) == PERSONA + NAMED + SIR
    assert persona({"assistant": "junk"}) == PERSONA + SIR


def test_name_stays_collapsed_and_clipped():
    long = "A" * 100
    assert persona(settings("name", "  Hiro \t  Tan ")) == PERSONA + BY_NAME
    assert (
        persona(settings("sir", long))
        == PERSONA + f" The owner's name is {'A' * 80}; use it sparingly." + SIR
    )


def test_voice_and_phone_routes_pick_up_the_address():
    from services.live_config import voice_instruction

    assert (
        voice_instruction(settings("maam", "Hiro Tan")) == PERSONA + NAMED + MAAM + " " + VOICE_LINE
    )
    assert voice_instruction({}) == PERSONA + SIR + " " + VOICE_LINE


def test_address_setting_defaults_merges_and_validates():
    assert ASSISTANT_DEFAULTS["address"] == "sir"
    store = {"tool_permissions": {}, "assistant": {"brain": "gemini", "owner_name": "Hiro"}}
    service = SettingsService(store, SettingsStore(None), [])
    service.apply(SettingsPatch(assistant={"brain": "claude"}))
    assert store["assistant"] == {"brain": "claude", "owner_name": "Hiro", "address": "sir"}
    for mode in ("maam", "name", "none", "sir"):
        service.apply(SettingsPatch.model_validate({"assistant": {"address": mode}}))
        assert store["assistant"]["address"] == mode
    for bad in ("Sir", "madam", "", " sir", None, 1, True, ["sir"], {"sir": 1}):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"assistant": {"address": bad}})
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate({"assistant": {"address": "sir", "title": "sir"}})


FORMS = re.compile(r"\b(sir|tuan|ma'am|puan)\b", re.IGNORECASE)


def test_third_party_call_prompts_do_not_use_the_owner_form_of_address():
    from calls import contracts
    from telephony import briefs

    shop, caller, owner = "+60312345678", "+60123455432", "+60111111111"
    prompts = {}
    for address in ("sir", "maam", "name", "none"):
        config = {
            "assistant": {"owner_name": "Hiro", "address": address},
            "calls": {"facts": "Open 9-5."},
        }
        calls = [
            briefs.screening_brief({"from": caller}, config),
            briefs.CallBrief(
                mode="owner_briefing",
                direction="outbound",
                counterpart=owner,
                owner_name=briefs.owner_name(config),
                briefing={
                    "caller_name": "Aiman",
                    "callback_number": caller,
                    "reason": "Parcel",
                    "urgency": "normal",
                    "message": "At the gate.",
                    "summary": "A parcel.",
                },
            ),
            briefs.CallBrief(
                mode="approved_callback",
                direction="outbound",
                counterpart=caller,
                owner_name=briefs.owner_name(config),
                message="On my way.",
                caller_name="Aiman",
            ),
            briefs.CallBrief(
                mode="task",
                direction="outbound",
                counterpart=shop,
                owner_name=briefs.owner_name(config),
                goal="Book a table",
                constraints={"time_window": "Friday 7-8 pm", "booking_name": "Hiro"},
            ),
        ]
        prompts[address] = [briefs.system_instruction(brief, now=0) for brief in calls]
        prompts[address] += [briefs.opening_line(brief) for brief in calls]
    # The setting never reaches a call prompt.
    assert prompts["sir"] == prompts["maam"] == prompts["name"] == prompts["none"]
    for text in [contracts.CALL_INSTRUCTION, briefs.COMMON, *prompts["sir"]]:
        assert not FORMS.search(text), text
