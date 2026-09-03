import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import database

def test_json_migration_process(tmp_path):
    test_json = tmp_path / "users_db.json"
    test_json.write_text(json.dumps({
        "users": {"1014915827": 2, "8559106318": 1},
        "air_notify_recipients": [1014915827]
    }))

    with patch("database.USERS_FILE", test_json), \
         patch("database.set_user_role", return_value=True) as mock_set_user, \
         patch("database.add_air_recipient", return_value=True) as mock_add_air, \
         patch("database.get_all_runtime_users", return_value={}):

        database.migrate_from_json_if_needed()

        assert mock_set_user.call_count == 2
        assert mock_add_air.call_count == 1
        assert not test_json.exists()
        assert Path(str(test_json) + ".bak").exists()
