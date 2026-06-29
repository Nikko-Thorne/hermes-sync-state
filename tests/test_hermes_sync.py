"""Tests for hermes-sync-state: crypto, packing, adapters."""

import io
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Load the hermes-sync script's functions into a namespace
# (it's a single-file script, not a package)
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "hermes-sync"
NS = {}

with open(SCRIPT_PATH) as f:
    code = f.read()
exec(code, NS)

# Save original HERMES_HOME so tests can restore it
ORIGINAL_HERMES_HOME = NS["HERMES_HOME"]


@pytest.fixture(autouse=True)
def _restore_hermes_home():
    """Restore HERMES_HOME after each test."""
    yield
    NS["HERMES_HOME"] = ORIGINAL_HERMES_HOME


class TestCrypto:
    """Encryption/decryption and key derivation."""

    def test_derive_key_deterministic(self):
        """Same seed always produces same key."""
        derive = NS["_derive_key"]
        k1 = derive("test seed")
        k2 = derive("test seed")
        assert k1 == k2
        assert len(k1) == 32  # 256-bit key

    def test_derive_key_different_seeds(self):
        """Different seeds produce different keys."""
        derive = NS["_derive_key"]
        k1 = derive("alpha")
        k2 = derive("beta")
        assert k1 != k2

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt then decrypt returns original data."""
        encrypt = NS["encrypt_state"]
        decrypt = NS["decrypt_state"]
        seed = "test seed phrase for encryption"
        plaintext = b"hello world" * 100

        blob = encrypt(seed, plaintext)
        assert blob != plaintext  # encrypted
        assert len(blob) == 12 + len(plaintext) + 16  # nonce + data + auth tag

        result = decrypt(seed, blob)
        assert result == plaintext

    def test_encrypt_different_seed_fails(self):
        """Decrypting with wrong seed raises error."""
        encrypt = NS["encrypt_state"]
        decrypt = NS["decrypt_state"]

        blob = encrypt("correct seed", b"secret data")

        with pytest.raises(Exception):
            decrypt("wrong seed", blob)

    def test_encrypt_empty_data(self):
        """Encrypting empty bytes works."""
        encrypt = NS["encrypt_state"]
        decrypt = NS["decrypt_state"]

        blob = encrypt("seed", b"")
        assert decrypt("seed", blob) == b""

    def test_encrypt_large_data(self):
        """Encrypting multi-megabyte data works."""
        encrypt = NS["encrypt_state"]
        decrypt = NS["decrypt_state"]
        seed = "large data seed"
        plaintext = b"x" * (1024 * 1024)  # 1MB

        blob = encrypt(seed, plaintext)
        assert decrypt(seed, blob) == plaintext

    def test_encrypt_nonce_is_random(self):
        """Two encryptions of same data produce different ciphertexts."""
        encrypt = NS["encrypt_state"]
        blob1 = encrypt("seed", b"same data")
        blob2 = encrypt("seed", b"same data")
        assert blob1 != blob2  # different nonce = different ciphertext


class TestPacking:
    """Pack/unpack state as tar.gz."""

    @pytest.fixture
    def hermes_home(self):
        tmp = tempfile.mkdtemp(prefix="hs-test-pack-")
        home = Path(tmp)
        (home / "skills" / "test-skill").mkdir(parents=True)
        (home / "skills" / "test-skill" / "SKILL.md").write_text("---\nname: test\n---\n# Test\n")
        (home / "memories").mkdir()
        (home / "memories" / "MEMORY.md").write_text("# Memory\n")
        (home / "cron").mkdir()
        (home / "cron" / "test.json").write_text('{"job": "test"}')
        yield home
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_pack_unpack_roundtrip(self, hermes_home):
        """Pack state to tar.gz and unpack back."""
        pack = NS["pack_state"]
        unpack = NS["unpack_state"]

        NS["HERMES_HOME"] = hermes_home
        tar_bytes = pack()
        assert len(tar_bytes) > 0

        # Unpack into a fresh directory
        fresh = hermes_home.parent / "fresh"
        fresh.mkdir(parents=True, exist_ok=True)
        NS["HERMES_HOME"] = fresh
        unpack(tar_bytes)

        assert (fresh / "skills" / "test-skill" / "SKILL.md").exists()
        assert (fresh / "memories" / "MEMORY.md").exists()
        assert (fresh / "cron" / "test.json").exists()

    def test_pack_skips_missing_dirs(self):
        """Packing when some dirs don't exist doesn't crash."""
        pack = NS["pack_state"]
        old_home = NS["HERMES_HOME"]
        NS["HERMES_HOME"] = Path("/nonexistent/hermes")
        try:
            result = pack()
        finally:
            NS["HERMES_HOME"] = old_home
        # Should return an empty tar.gz
        assert isinstance(result, bytes)
        # Verify it's a valid (empty) tar.gz
        buf = io.BytesIO(result)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            assert len(names) == 0

    def test_pack_preserves_file_content(self, hermes_home):
        """File content survives pack→unpack unchanged."""
        pack = NS["pack_state"]
        unpack = NS["unpack_state"]

        NS["HERMES_HOME"] = hermes_home
        tar_bytes = pack()

        fresh = hermes_home.parent / "fresh2"
        fresh.mkdir(parents=True, exist_ok=True)
        NS["HERMES_HOME"] = fresh
        unpack(tar_bytes)

        original = hermes_home / "skills" / "test-skill" / "SKILL.md"
        restored = fresh / "skills" / "test-skill" / "SKILL.md"
        assert restored.read_text() == original.read_text()


class TestBraveAdapter:
    """Brave Sync adapter push/pull with mocked relay."""

    def test_push_without_seed(self, capsys):
        """Push without seed prints helpful error."""
        BraveAdapter = NS["BraveAdapter"]
        BraveAdapter.push({"seed": ""})
        out = capsys.readouterr().out
        assert "No seed" in out

    def test_push_without_relay(self, capsys):
        """Push without RELAY env var prints helpful error."""
        BraveAdapter = NS["BraveAdapter"]
        BraveAdapter.RELAY = ""
        BraveAdapter.push({"seed": "test test test"})
        out = capsys.readouterr().out
        assert "HERMES_SYNC_RELAY" in out
        BraveAdapter.RELAY = "https://test.workers.dev"  # restore

    def test_pull_without_seed(self, capsys):
        """Pull without seed prints helpful error."""
        BraveAdapter = NS["BraveAdapter"]
        BraveAdapter.pull({"seed": ""})
        out = capsys.readouterr().out
        assert "No seed" in out

    def test_push_pull_integration(self, hermes_home, monkeypatch):
        """Roundtrip: pack→encrypt→push mock→pull→decrypt→unpack."""
        # This test exercises the full pipeline with a real relay-like mock.
        # We intercept requests.put/get to simulate the Cloudflare worker.

        pack = NS["pack_state"]
        unpack = NS["unpack_state"]
        BraveAdapter = NS["BraveAdapter"]

        # Store encrypted blobs in a dict (simulates R2)
        store = {}
        import requests

        def mock_put(url, data, timeout):
            hash_key = url.split("/")[-1]
            store[hash_key] = data
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            return resp

        def mock_get(url, timeout):
            hash_key = url.split("/")[-1]
            resp = MagicMock()
            if hash_key in store:
                resp.content = store[hash_key]
                resp.status_code = 200
            else:
                resp.status_code = 404
            resp.raise_for_status = MagicMock()
            if resp.status_code != 200:
                resp.raise_for_status.side_effect = requests.HTTPError("404")
            return resp

        seed = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        cfg = {"seed": seed, "adapter": "brave"}

        # Push
        NS["HERMES_HOME"] = hermes_home
        tar_bytes = pack()

        with patch("requests.put", mock_put):
            BraveAdapter.push(cfg)

        assert len(store) == 1
        blob = list(store.values())[0]
        assert blob != tar_bytes  # encrypted

        # Pull into fresh directory
        fresh = hermes_home.parent / "fresh-integration"
        fresh.mkdir(parents=True, exist_ok=True)

        with patch("requests.get", mock_get):
            NS["HERMES_HOME"] = fresh
            BraveAdapter.pull(cfg)

        assert (fresh / "skills" / "test-skill" / "SKILL.md").exists()
        assert (fresh / "memories" / "MEMORY.md").exists()

    @pytest.fixture
    def hermes_home(self):
        tmp = tempfile.mkdtemp(prefix="hs-test-brave-")
        home = Path(tmp)
        (home / "skills" / "test-skill").mkdir(parents=True)
        (home / "skills" / "test-skill" / "SKILL.md").write_text("---\nname: test\n---\n# Brave Test\n")
        (home / "memories").mkdir()
        (home / "memories" / "MEMORY.md").write_text("# Brave Memory\n")
        (home / "cron").mkdir()
        yield home
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


class TestConfig:
    """Configuration file handling."""

    def test_config_roundtrip(self, tmp_path):
        """Save and load config."""
        cfg = {"adapter": "brave", "seed": "test seed phrase"}
        config_path = tmp_path / ".sync-config.json"
        config_path.write_text(json.dumps(cfg, indent=2))

        loaded = json.loads(config_path.read_text())
        assert loaded["adapter"] == "brave"
        assert loaded["seed"] == "test seed phrase"


class TestAdaptersExist:
    """All four adapters are defined and have push/pull."""

    def test_brave_adapter(self):
        BraveAdapter = NS["BraveAdapter"]
        assert hasattr(BraveAdapter, "push")
        assert hasattr(BraveAdapter, "pull")

    def test_git_adapter(self):
        GitAdapter = NS["GitAdapter"]
        assert hasattr(GitAdapter, "push")
        assert hasattr(GitAdapter, "pull")

    def test_local_adapter(self):
        LocalAdapter = NS["LocalAdapter"]
        assert hasattr(LocalAdapter, "push")
        assert hasattr(LocalAdapter, "pull")

    def test_s3_adapter(self):
        S3Adapter = NS["S3Adapter"]
        assert hasattr(S3Adapter, "push")
        assert hasattr(S3Adapter, "pull")

    def test_adapters_registry(self):
        """All adapters are in the ADAPTERS dict."""
        adapters = NS["ADAPTERS"]
        assert "brave" in adapters
        assert "git" in adapters
        assert "local" in adapters
        assert "s3" in adapters
        assert len(adapters) == 4


class TestDependencyCheck:
    """Auto-install dependency check."""

    def test_deps_already_installed(self):
        """_check_deps returns True when all deps are available."""
        assert NS["_check_deps"]() is True

    def test_required_deps_list(self):
        """REQUIRED_DEPS dict has expected packages."""
        deps = NS["REQUIRED_DEPS"]
        assert "bip39" in deps
        assert "cryptography" in deps
        assert "requests" in deps
        assert deps["bip39"] == "bip39"
