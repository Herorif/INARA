"""S13a interface sounds: the ``sound`` settings block (docs/SOUND.md). Defaults, validation
and the patch merge; no audio is involved."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from services.settings import SOUND_DEFAULTS, SettingsPatch, SettingsService, sound_settings


def test_defaults():
    assert SOUND_DEFAULTS == {"enabled": True, "volume": 0.5, "thinking": False}
    assert sound_settings({}) == SOUND_DEFAULTS
    assert sound_settings(None) == SOUND_DEFAULTS
    assert sound_settings({"sound": "loud"}) == SOUND_DEFAULTS


def test_saved_values_over_defaults_and_bad_values_fall_back():
    assert sound_settings({"sound": {"enabled": False}}) == {
        "enabled": False, "volume": 0.5, "thinking": False,
    }
    assert sound_settings({"sound": {"volume": 0.257, "thinking": True}}) == {
        "enabled": True, "volume": 0.26, "thinking": True,
    }
    for bad in (1.5, -0.1, True, "0.5", None, float("nan")):
        assert sound_settings({"sound": {"volume": bad}})["volume"] == 0.5
    assert sound_settings({"sound": {"enabled": "no", "thinking": 1}}) == SOUND_DEFAULTS


@pytest.mark.parametrize("bad", [
    {}, {"enabled": None}, {"volume": None}, {"thinking": None},
    {"enabled": "true"}, {"enabled": 1}, {"thinking": "yes"},
    {"volume": 1.01}, {"volume": -0.01}, {"volume": True}, {"volume": "0.5"},
    {"volume": float("nan")}, {"volume": float("inf")}, {"other": True},
])
def test_patch_validation_rejects(bad):
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate({"sound": bad})


def test_volume_is_rounded_to_two_decimals():
    patch = SettingsPatch.model_validate({"sound": {"volume": 0.333}})
    assert patch.model_dump(exclude_unset=True) == {"sound": {"volume": 0.33}}
    assert SettingsPatch.model_validate({"sound": {"volume": 1}}).sound.volume == 1.0
    assert SettingsPatch.model_validate({"sound": {"volume": 0}}).sound.volume == 0.0


def test_patch_merges_with_defaults_and_saves():
    saved = []
    service = SettingsService({}, SimpleNamespace(save=saved.append), [])
    snapshot = service.apply(SettingsPatch.model_validate({"sound": {"volume": 0.8}}))
    assert snapshot["sound"] == {"enabled": True, "volume": 0.8, "thinking": False}
    snapshot = service.apply(SettingsPatch.model_validate({"sound": {"enabled": False}}))
    assert snapshot["sound"] == {"enabled": False, "volume": 0.8, "thinking": False}
    snapshot = service.apply(SettingsPatch.model_validate({"sound": {"thinking": True}}))
    assert snapshot["sound"] == {"enabled": False, "volume": 0.8, "thinking": True}
    assert saved[-1]["sound"] == snapshot["sound"]
    assert len(saved) == 3
