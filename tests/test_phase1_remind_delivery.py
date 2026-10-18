"""Phase 1 — Bảo đảm giao hàng reminder (H1 + H2 trong docs/BAO CAO_AUDIT_LOI_AN).

Hai bất biến phía người dùng, không phải cờ nội bộ:
  H1. Nhắc nhở CHỈ biến mất khi bot đã gửi được thành công.
  H2. Một row hỏng không được chặn những nhắc nhở xếp sau nó.
"""
import logging
import time

import pytest


class _Avatar:
    url = "https://cdn.discordapp.com/embed/avatars/0.png"


class _UserLike:
    def __init__(self, uid: int, fail: bool = False):
        self.id = uid
        self.mention = f"<@{uid}>"
        self.fail = fail
        self.sent = []
        self.display_avatar = _Avatar()

    async def send(self, content=None, embed=None, **kwargs):
        if self.fail:
            raise RuntimeError("Cannot send to user (DM closed)")
        self.sent.append(content)


class _ChannelLike:
    def __init__(self, cid: int, fail: bool = False):
        self.id = cid
        self.fail = fail
        self.sent = []

    async def send(self, content=None, embed=None, **kwargs):
        if self.fail:
            raise RuntimeError("Missing Access")
        self.sent.append(content)


class _FakeBot:
    def __init__(self, channels=None, users=None):
        self.channels = channels or {}
        self.users = users or {}
        self.user = _UserLike(999)

    def get_channel(self, cid):
        return self.channels.get(cid)

    def get_user(self, uid):
        return self.users.get(uid)

    async def fetch_user(self, uid):
        raise RuntimeError("404 Not Found")


@pytest.fixture()
def make_cog(temp_db, monkeypatch):
    from cogs.remind import Remind

    monkeypatch.setattr(Remind.reminder_task, "start", lambda *a, **k: None)

    def build(channels=None, users=None):
        bot = _FakeBot(channels or {}, users or {})
        return Remind(bot), bot

    return build


async def _add(user_id, channel_id, reason="uống thuốc", guild_id=""):
    from database import async_add_reminder
    return await async_add_reminder(str(user_id), guild_id, str(channel_id), reason,
                                    int(time.time()) - 10)   # đã đến hạn


async def _due_rows():
    from database import async_get_due_reminders
    return await async_get_due_reminders(int(time.time()))


async def test_failed_delivery_does_not_delete_the_reminder(make_cog):
    """H1: kênh từ chối + user tắt DM -> nhắc nhở phải còn đó, đếm thêm 1 lần thử."""
    await _add(111, 555)
    cog, _bot = make_cog(
        channels={555: _ChannelLike(555, fail=True)},
        users={111: _UserLike(111, fail=True)},
    )

    await cog._deliver_due_reminders()

    rows = await _due_rows()
    assert len(rows) == 1, "nhắc nhở chưa gửi được mà đã bị xóa mất"
    assert rows[0]["reason"] == "uống thuốc"
    assert int(rows[0]["attempts"]) == 1


async def test_third_failure_is_dropped_and_logged(make_cog, caplog):
    """Retry có trần: lần thử thứ 3 thất bại thì bỏ + log cảnh báo (không quét mãi mỗi phút)."""
    from database import async_set_reminder_attempts
    from cogs.remind import REMIND_MAX_ATTEMPTS
    rid = await _add(222, 666)
    await async_set_reminder_attempts(rid, REMIND_MAX_ATTEMPTS - 1)
    cog, _bot = make_cog(
        channels={666: _ChannelLike(666, fail=True)},
        users={222: _UserLike(222, fail=True)},
    )

    with caplog.at_level(logging.WARNING, logger="BotV2.Remind"):
        await cog._deliver_due_reminders()

    assert await _due_rows() == [], "hết lượt retry mà row vẫn nằm lại hàng đợi"
    assert "Bỏ nhắc nhở" in caplog.text, caplog.text


async def test_successful_delivery_deletes_immediately(make_cog):
    channel = _ChannelLike(777)
    await _add(333, 777)
    cog, _bot = make_cog(channels={777: channel}, users={333: _UserLike(333)})

    await cog._deliver_due_reminders()

    assert channel.sent, "lẽ ra phải gửi được vào kênh"
    assert await _due_rows() == []


async def test_poison_row_does_not_block_the_rest_of_the_batch(make_cog, caplog):
    """H2: row user_id rác đứng TRƯỚC, nhắc nhở khỏe mạnh phía sau vẫn phải được gửi."""
    from database import async_add_reminder
    poison = int(time.time()) - 30
    healthy = int(time.time()) - 10
    await async_add_reminder("khong-phai-cong-so", "", "", "row rac", poison)
    good_channel = _ChannelLike(888)
    await async_add_reminder("444", "", "888", "họp 9h", healthy)

    cog, _bot = make_cog(channels={888: good_channel}, users={444: _UserLike(444)})

    with caplog.at_level(logging.ERROR, logger="BotV2.Remind"):
        await cog._deliver_due_reminders()

    assert good_channel.sent, (
        "nhắc nhở lành bị chết đói vì một row hỏng đứng trước"
    )
    assert "raise lỗi" in caplog.text, "lỗi row hỏng bị nuốt không lại log"


async def test_dm_fallback_used_when_channel_is_gone(make_cog):
    """Kênh bị xóa (get_channel trả None) thì vẫn phải tới user qua DM."""
    user = _UserLike(555)
    await _add(555, 999)
    cog, _bot = make_cog(channels={}, users={555: user})

    await cog._deliver_due_reminders()

    assert user.sent, "không gửi kênh được thì phải fallback sang DM"
    assert await _due_rows() == []
