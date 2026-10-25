"""P0-1 — Cách ly tenant cho ticket panel & reaction-role panel.

Lỗi gốc: UPDATE panel cha có scope guild nhưng không kiểm rowcount, rồi vẫn
DELETE/INSERT bảng con chỉ theo panel_id. Admin guild A có thể thay/xóa nút của
panel thuộc guild B bằng cách gửi panel.id của B trong JSON.
"""
import pytest

GUILD_A = "900000000000000001"
GUILD_B = "900000000000000002"


def _ticket(db, guild_id, name, labels):
    return db.save_ticket_panel(
        guild_id,
        {"name": name, "channel_id": "100"},
        [{"label": label, "category_id": "1"} for label in labels],
    )


def _reaction(db, guild_id, name, emojis):
    return db.save_reaction_roles_panel(
        guild_id,
        {"name": name, "channel_id": "200"},
        [{"emoji": emoji, "role_id": "1"} for emoji in emojis],
    )


def test_save_cannot_hijack_foreign_ticket_panel(temp_db):
    import database as db

    panel_a = _ticket(db, GUILD_A, "panel-A", ["A-1"])
    panel_b = _ticket(db, GUILD_B, "panel-B", ["B-1", "B-2"])
    assert panel_a and panel_b

    ret = db.save_ticket_panel(
        GUILD_A,
        {"id": panel_b, "name": "HIJACKED", "channel_id": "999"},
        [{"label": "ATTACK", "category_id": "666"}],
    )
    assert ret == 0, "save vào panel của guild khác phải bị từ chối"

    panel = db.get_ticket_panel(panel_b)
    assert panel["name"] == "panel-B"
    assert [b["label"] for b in panel["buttons"]] == ["B-1", "B-2"]
    assert [b["category_id"] for b in panel["buttons"]] == ["1", "1"]


def test_delete_cannot_remove_foreign_ticket_children(temp_db):
    import database as db

    panel_b = _ticket(db, GUILD_B, "panel-B", ["B-1", "B-2"])
    deleted = db.delete_ticket_panel(panel_b, GUILD_A)

    assert deleted is False, "delete xuyên guild phải trả False"
    panel = db.get_ticket_panel(panel_b)
    assert panel is not None, "panel của guild B bị xóa"
    assert len(panel["buttons"]) == 2, "nút của panel guild B bị xóa"


def test_save_cannot_hijack_foreign_reaction_panel(temp_db):
    import database as db

    panel_b = _reaction(db, GUILD_B, "rr-B", ["B", "C"])
    ret = db.save_reaction_roles_panel(
        GUILD_A,
        {"id": panel_b, "name": "HIJACKED", "channel_id": "999"},
        [{"emoji": "X", "role_id": "999999"}],
    )
    assert ret == 0

    panel = db.get_reaction_roles_panel(panel_b)
    assert panel["name"] == "rr-B"
    assert [(i["emoji"], i["role_id"]) for i in panel["items"]] == [("B", "1"), ("C", "1")]


def test_delete_cannot_remove_foreign_reaction_children(temp_db):
    import database as db

    panel_b = _reaction(db, GUILD_B, "rr-B", ["B", "C"])
    assert db.delete_reaction_roles_panel(panel_b, GUILD_A) is False
    panel = db.get_reaction_roles_panel(panel_b)
    assert panel is not None and len(panel["items"]) == 2


def test_getters_are_scoped_to_guild(temp_db):
    import database as db

    panel_b = _ticket(db, GUILD_B, "panel-B", ["B-1"])
    rr_b = _reaction(db, GUILD_B, "rr-B", ["B"])

    assert db.get_ticket_panel(panel_b, GUILD_A) is None
    assert db.get_ticket_panel(panel_b, GUILD_B) is not None
    assert db.get_reaction_roles_panel(rr_b, GUILD_A) is None
    assert db.get_reaction_roles_panel(rr_b, GUILD_B) is not None


def test_message_id_update_is_scoped_to_guild(temp_db):
    import database as db

    panel_b = _ticket(db, GUILD_B, "panel-B", ["B-1"])
    rr_b = _reaction(db, GUILD_B, "rr-B", ["B"])

    assert db.update_panel_message_id(panel_b, GUILD_A, "evil") is False
    assert db.update_reaction_roles_message_id(rr_b, GUILD_A, "evil") is False
    assert db.get_ticket_panel(panel_b, GUILD_B)["message_id"] is None
    assert db.get_reaction_roles_panel(rr_b, GUILD_B)["message_id"] is None

    assert db.update_panel_message_id(panel_b, GUILD_B, "msg-1") is True
    assert db.update_reaction_roles_message_id(rr_b, GUILD_B, "msg-2") is True
    assert db.get_ticket_panel(panel_b, GUILD_B)["message_id"] == "msg-1"
    assert db.get_reaction_roles_panel(rr_b, GUILD_B)["message_id"] == "msg-2"


def test_panel_routes_reject_foreign_panel_id(client, temp_db):
    """Route phải trả 404 và không được ghi gì khi panel.id thuộc guild khác."""
    import database as db
    from conftest import MOCK_USER_ID, set_csrf_token

    panel_b = _ticket(db, GUILD_B, "panel-B", ["B-1"])
    from conftest import login

    login(client, user_id=MOCK_USER_ID, guild_id=GUILD_A)
    token = set_csrf_token(client)

    resp = client.post(
        f"/api/guild/{GUILD_A}/tickets",
        json={"panel": {"id": panel_b, "name": "HIJACK", "channel_id": "1"}, "buttons": []},
        headers={"X-CSRF-Token": token, "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)[:300]
    assert len(db.get_ticket_panel(panel_b)["buttons"]) == 1
