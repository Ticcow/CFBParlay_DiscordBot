from bot.commands import patch_notes
from bot.parlays import repository


class FakeBot:
    def __init__(self, conn):
        self.conn = conn
        self.announcements = []

    async def announce(self, message):
        self.announcements.append(message)


async def test_first_run_ever_just_starts_tracking_without_announcing(conn, monkeypatch):
    monkeypatch.setattr(patch_notes, "_current_commit", lambda: "abc123")
    bot = FakeBot(conn)

    await patch_notes.announce_if_updated(bot)

    assert bot.announcements == []
    assert repository.get_state(conn, patch_notes.STATE_KEY) == "abc123"


async def test_same_commit_as_last_time_does_not_announce(conn, monkeypatch):
    monkeypatch.setattr(patch_notes, "_current_commit", lambda: "abc123")
    repository.set_state(conn, patch_notes.STATE_KEY, "abc123")
    bot = FakeBot(conn)

    await patch_notes.announce_if_updated(bot)

    assert bot.announcements == []


async def test_new_commit_announces_subjects_since_last_and_updates_state(conn, monkeypatch):
    monkeypatch.setattr(patch_notes, "_current_commit", lambda: "def456")
    monkeypatch.setattr(
        patch_notes, "_commit_subjects_since", lambda old, new: ["Fix bug X", "Add feature Y"]
    )
    repository.set_state(conn, patch_notes.STATE_KEY, "abc123")
    bot = FakeBot(conn)

    await patch_notes.announce_if_updated(bot)

    assert len(bot.announcements) == 1
    assert "Fix bug X" in bot.announcements[0]
    assert "Add feature Y" in bot.announcements[0]
    assert repository.get_state(conn, patch_notes.STATE_KEY) == "def456"


async def test_no_git_available_does_nothing(conn, monkeypatch):
    monkeypatch.setattr(patch_notes, "_current_commit", lambda: None)
    bot = FakeBot(conn)

    await patch_notes.announce_if_updated(bot)

    assert bot.announcements == []
    assert repository.get_state(conn, patch_notes.STATE_KEY) is None


async def test_caps_shown_commits_and_notes_remainder(conn, monkeypatch):
    monkeypatch.setattr(patch_notes, "_current_commit", lambda: "def456")
    many_subjects = [f"commit {i}" for i in range(20)]
    monkeypatch.setattr(patch_notes, "_commit_subjects_since", lambda old, new: many_subjects)
    repository.set_state(conn, patch_notes.STATE_KEY, "abc123")
    bot = FakeBot(conn)

    await patch_notes.announce_if_updated(bot)

    assert "...and 5 more" in bot.announcements[0]


async def test_empty_diff_updates_state_without_announcing(conn, monkeypatch):
    monkeypatch.setattr(patch_notes, "_current_commit", lambda: "def456")
    monkeypatch.setattr(patch_notes, "_commit_subjects_since", lambda old, new: [])
    repository.set_state(conn, patch_notes.STATE_KEY, "abc123")
    bot = FakeBot(conn)

    await patch_notes.announce_if_updated(bot)

    assert bot.announcements == []
    assert repository.get_state(conn, patch_notes.STATE_KEY) == "def456"
