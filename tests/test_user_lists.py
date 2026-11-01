import os

from fuzzer_engine import FuzzerEngine
from user_lists import EXCLUDE, INCLUDE, UserLists


def test_ensure_creates_user_files(tmp_path):
    store = UserLists(str(tmp_path / "lists"))
    store.ensure()
    assert os.path.isfile(store.path(INCLUDE))
    assert os.path.isfile(store.path(EXCLUDE))
    assert store.load(INCLUDE) == []


def test_add_deduplicate_and_preserve_comments(tmp_path):
    store = UserLists(str(tmp_path / "lists"))
    store.ensure()
    with open(store.path(INCLUDE), "w", encoding="utf-8") as handle:
        handle.write("# personal list\nold.example\n")

    added, invalid = store.add(
        INCLUDE,
        ["YouTube.com", "youtube.com", "bad_domain", "discord.com"],
    )
    assert added == 2
    assert invalid == []
    assert store.load(INCLUDE) == ["old.example", "youtube.com", "discord.com"]
    assert "# personal list" in store.read_lines(INCLUDE)


def test_save_filters_invalid_and_reports(tmp_path):
    store = UserLists(str(tmp_path / "lists"))
    saved, invalid = store.save_lines(
        EXCLUDE,
        ["example.com", "не_домен", "", "# note", "example.com"],
    )
    assert saved == 1
    assert invalid == ["не_домен"]
    assert store.load(EXCLUDE) == ["example.com"]
    assert "# note" in store.read_lines(EXCLUDE)


def test_remove(tmp_path):
    store = UserLists(str(tmp_path / "lists"))
    store.save(INCLUDE, ["a.com", "b.com", "c.com"])
    removed = store.remove(INCLUDE, ["B.COM"])
    assert removed == 1
    assert store.load(INCLUDE) == ["a.com", "c.com"]


def test_engine_sync_respects_exclusions(tmp_path):
    bat = tmp_path / "strategy.bat"
    bat.write_text("winws.exe --dpi-desync=split\n", encoding="utf-8")
    lists_dir = tmp_path / "lists"
    store = UserLists(str(lists_dir))
    store.save(EXCLUDE, ["blocked.example"])

    engine = FuzzerEngine(bat_path=str(bat))
    engine.log_callback = lambda _message: None
    engine.sync_hosts_to_user_list(["youtube.com", "blocked.example"])

    assert store.load(INCLUDE) == ["youtube.com"]
    assert store.load(EXCLUDE) == ["blocked.example"]
