"""DUP-01~05 单一事实源、同名消歧与重复资源退役判据。"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_providerTypeHasOneCanonicalEnumAndInterfaceHasNoLegacyEntry():
    from neurova.llm.interfaces import provider_interface
    from neurova.llm.providers.types import ProviderType
    from neurova.llm.triage import SmallBrainTriageGate
    from neurova.llm.adapters.openai_adapter import OpenAIAdapter
    from neurova.llm.registry.provider_registry import ProviderRegistry

    assert not hasattr(provider_interface, "ProviderType")
    assert {member.value for member in ProviderType} == {
        "openai", "anthropic", "gemini", "ollama", "openrouter", "opencode", "custom",
    }
    assert OpenAIAdapter(provider_interface.ProviderConfig(api_key="offline")).provider_type is ProviderType.OPENAI
    registry = ProviderRegistry()
    assert registry._providers[ProviderType.OPENAI] is OpenAIAdapter
    triage_source = (REPO_ROOT / "neurova/llm/triage.py").read_text(encoding="utf-8")
    assert "from neurova.llm.providers.types import" in triage_source
    assert SmallBrainTriageGate.__module__ == "neurova.llm.triage"


def test_registryListsUnregisteredCanonicalProvidersWithoutInventingAdapters():
    from neurova.llm.providers.types import ProviderType
    from neurova.llm.registry.provider_registry import ProviderRegistry

    rows = ProviderRegistry().list_available_providers()
    assert {row["type"] for row in rows} == {member.value for member in ProviderType}
    assert [row["type"] for row in rows if row["registered"]] == ["openai"]
    assert next(row for row in rows if row["type"] == "custom")["class"] is None


def test_memoryEmotionAnalyzerIsDistinctFromContextEmotionAnalyzer():
    from neurova.cognitive_layers.memory_layer import emotion as memory_emotion
    from neurova.cognitive_layers.emotion_context_layer import emotion as context_emotion
    from neurova.memory import MemoryEmotionAnalyzer as exported

    assert not hasattr(memory_emotion, "EmotionAnalyzer")
    assert exported is memory_emotion.MemoryEmotionAnalyzer
    assert exported is not context_emotion.EmotionAnalyzer
    assert memory_emotion.get_emotion_analyzer_instance().__class__ is exported
    assert exported(use_legacy=True).analyze("开心")["primary_emotion"] in {"joy", "neutral"}
    assert context_emotion.EmotionAnalyzer(agent_id="dup-01-context")._agent_id == "dup-01-context"


def test_capabilityPresetIsDistinctFromUserModelPreset():
    from neurova.llm.capability_detector import (
        ModelCapabilityPreset,
        apply_preset_defaults,
        lookup_model_preset,
    )
    from neurova.llm.presets import ModelPreset
    from neurova.llm import capability_detector

    assert not hasattr(capability_detector, "ModelPreset")
    assert ModelCapabilityPreset is not ModelPreset
    preset = lookup_model_preset("gpt-4o")
    assert isinstance(preset, ModelCapabilityPreset)
    assert apply_preset_defaults("gpt-4o", {"capabilities": []})["context_window"] == 128_000
    user_preset = ModelPreset(name="offline", provider="custom", model_id="offline")
    assert user_preset.to_dict()["name"] == "offline"


def test_commerceFallbackKeysOnlyCoverSheinAndSpecializedKeysRemain():
    from neurova.collaboration.neurflow import external_api as api

    assert api.COMMERCE_KEY_NAMES == {"shein": ["NEUROVA_SHEIN_API_KEY"]}
    assert api.TAOBAO_KEY_NAMES == {
        "app_key": ["NEUROVA_TAOBAO_APP_KEY"],
        "app_secret": ["NEUROVA_TAOBAO_APP_SECRET"],
        "access_token": ["NEUROVA_TAOBAO_ACCESS_TOKEN"],
        "refresh_token": ["NEUROVA_TAOBAO_REFRESH_TOKEN"],
    }
    assert api.AMAZON_SP_KEY_NAMES == {
        "refresh_token": ["NEUROVA_AMAZON_SP_REFRESH_TOKEN"],
        "client_id": ["NEUROVA_AMAZON_SP_CLIENT_ID"],
        "client_secret": ["NEUROVA_AMAZON_SP_CLIENT_SECRET"],
    }


def test_androidManifestUsesOnlyLiveLauncherResource():
    manifest_path = REPO_ROOT / "Mobile/android-native/app/src/main/AndroidManifest.xml"
    res_root = manifest_path.parent / "res"
    manifest = ET.parse(manifest_path).getroot()
    icon = manifest.find("application").attrib["{http://schemas.android.com/apk/res/android}icon"]
    assert icon == "@mipmap/ic_launcher"
    assert (res_root / "mipmap-anydpi-v26/ic_launcher.xml").is_file()
    assert not (res_root / "mipmap-anydpi-v26/ic_launcher_round.xml").exists()


def test_muscleBackupsKeepOnlyLatestDuplicateAndDistinctTicketSnapshot():
    ledger = REPO_ROOT / "docs/05-reports/muscle-memory-ledger"
    expected = {
        "muscle_l2.json.pre-muscle-ngram-20260921T174800Z":
            "c507241f6670b51e0bf967f65c6a919e825a634168f55940d4c11bafb216bff7",
        "muscle_l2.json.pre-muscle-ngram-20261025T191358Z":
            "c2cef740f23af75df3c9807b768f7938c4cf063b990966b5a89c1294302faf52",
    }
    assert {path.name for path in ledger.glob("muscle_l2.json.pre-muscle-ngram-*")} == set(expected)
    for name, digest in expected.items():
        assert hashlib.sha256((ledger / name).read_bytes()).hexdigest() == digest
        json.loads((ledger / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("package", ["tests.performance", "tests.performance.memory"])
def test_performancePackageImportDoesNotMutateSysPath(package):
    code = (
        "import sys\n"
        "before = list(sys.path)\n"
        f"import {package}\n"
        "assert sys.path == before, (package_name, before, sys.path)\n"
    ).replace("package_name", repr(package))
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
