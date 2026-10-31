import hashlib
import logging

import pytest

from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.config import Settings
from hdrp_agent.domain import AgentError
from hdrp_agent.logging import SecretFilter
from hdrp_agent.store import Store


def test_immutable_artifacts_and_symlink_rejection(tmp_path):
    settings = Settings(tmp_path)
    objects = ArtifactStore(settings.state / "artifacts", Store(settings.db_path))
    digest = objects.put(b"proof", "application/json")
    assert objects.read(digest) == b"proof"
    assert objects.put(b"proof", "application/json", expected=digest) == digest
    with pytest.raises(AgentError): objects.put(b"other", expected=digest)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    prefix = objects.root / "ff"
    prefix.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AgentError): objects.read("f" * 64)


def test_transaction_rolls_back_and_idempotency_conflicts(tmp_path):
    store = Store(tmp_path / "state.db")
    def action(c):
        store.event(c, "subject", "test", {})
        return {"ok": True}
    assert store.idempotent("scope", "key", {}, action) == {"ok": True}
    assert store.idempotent("scope", "key", {}, action) == {"ok": True}
    with pytest.raises(AgentError): store.idempotent("scope", "key", {"different": True}, action)
    with store.connect() as c: assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_secret_filter_and_settings_repr(tmp_path):
    settings = Settings(tmp_path, api_key="test-secret", token="local-secret")
    assert "test-secret" not in repr(settings)
    assert "local-secret" not in repr(settings)
    record = logging.LogRecord("test", logging.INFO, "", 0, "Authorization: Bearer %s key=%s", ("local-secret", "test-secret"), None)
    SecretFilter([settings.api_key, settings.token]).filter(record)
    assert "test-secret" not in record.getMessage()
    assert "local-secret" not in record.getMessage()


def test_artifact_root_and_database_cannot_escape_through_symlinks(tmp_path):
    state=tmp_path/'state';state.mkdir();outside=tmp_path/'outside';outside.mkdir()
    (state/'artifacts').symlink_to(outside,target_is_directory=True)
    store=Store(state/'ledger.db')
    with pytest.raises(AgentError):ArtifactStore(state/'artifacts',store)
    (outside/'db').write_bytes(b'')
    (state/'linked.db').symlink_to(outside/'db')
    with pytest.raises(AgentError):Store(state/'linked.db')
