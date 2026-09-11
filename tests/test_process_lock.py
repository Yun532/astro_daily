from astro_daily.process_lock import _is_stale


def test_dead_pid_lock_is_stale_without_waiting_for_timeout(tmp_path):
    lock = tmp_path / "source-fetch.lock"
    lock.write_text("pid=99999999\ncreated=0\n", encoding="utf-8")

    assert _is_stale(lock, stale_after_seconds=10800)
