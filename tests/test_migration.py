import json
from pathlib import Path
from unittest.mock import patch

import tuyabot.storage.sqlite_store as database


def test_json_migration_process(tmp_path):
    test_json = tmp_path / "users_db.json"
    test_json.write_text(json.dumps({
        "users": {"111111111": 2, "222222222": 1},
        "air_notify_recipients": [111111111]
    }))

    with patch("tuyabot.storage.sqlite_store.USERS_FILE", test_json), \
         patch("tuyabot.storage.sqlite_store.set_user_role", return_value=True) as mock_set_user, \
         patch("tuyabot.storage.sqlite_store.add_air_recipient", return_value=True) as mock_add_air, \
         patch("tuyabot.storage.sqlite_store.get_all_runtime_users", return_value={}):

        database.migrate_from_json_if_needed()

        assert mock_set_user.call_count == 2
        assert mock_add_air.call_count == 1
        assert not test_json.exists()
        assert Path(str(test_json) + ".bak").exists()
