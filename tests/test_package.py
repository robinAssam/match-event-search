from match_event_search.config import DATA_DIR


def test_data_dir_is_inside_repo():
    assert DATA_DIR.parts[-2:] == ("data", "raw")
