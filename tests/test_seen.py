from datetime import date

from astro_daily.models import Paper
from astro_daily.seen import SeenStore, deduplicate_papers


def paper(paper_id: str, title: str = "Title") -> Paper:
    return Paper(paper_id=paper_id, title=title, url=f"https://example.com/{paper_id}", source="test")


def test_missing_seen_file_is_empty(tmp_path):
    store = SeenStore.load(tmp_path / "seen.json")
    assert not store.is_seen(paper("1"))


def test_mark_and_reload_seen_file(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore.load(path)
    item = paper("1")
    store.mark_many([item], seen_date=date(2026, 5, 2))
    store.save()
    loaded = SeenStore.load(path)
    assert loaded.is_seen(item)


def test_deduplicate_by_title():
    first = paper("1", "Same Title")
    second = paper("2", " same   title ")
    assert deduplicate_papers([first, second]) == [first]
