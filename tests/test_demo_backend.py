"""The demo backend, which is what somebody sees before configuring anything.

It is also what the screenshots are taken against, so its failures are the ones
most likely to be met by a person who has not decided to trust this yet.
"""

import json

import pytest

from gtkpass.backends import BackendError
from gtkpass.backends.demo import DemoBackend, DemoBackendSettings

SAMPLE = [{"name": "example/entry", "content": "hunter2\nusername: someone"}]


class TestTheBuiltInData:
    def test_entries_can_be_opened(self):
        backend = DemoBackend.create()

        name = backend.list_passwords()[0].name

        assert backend.get_password(name).password


class TestTheFallbackWhenThePackagedDataIsUnreadable:
    """The packaged JSON is read through importlib.resources, which can fail.

    A zipped or badly built wheel is the realistic way, and the fallback existed
    for exactly that -- but it was written in a shape the reader does not
    understand, so it turned one failure into a KeyError somewhere else.
    """

    @pytest.fixture
    def without_packaged_data(self, monkeypatch):
        def unreadable(*_args, **_kwargs):
            raise OSError("no packaged data here")

        monkeypatch.setattr("gtkpass.backends.demo.files", unreadable)

    def test_it_still_lists_something(self, without_packaged_data):
        assert DemoBackend.create().list_passwords()

    def test_and_that_something_can_be_opened(self, without_packaged_data):
        backend = DemoBackend.create()

        name = backend.list_passwords()[0].name

        assert backend.get_password(name).password


class TestCustomData:
    """The setting names a demo.json, and used to be read as its directory."""

    @pytest.fixture
    def custom(self, tmp_path):
        path = tmp_path / "mine.json"
        path.write_text(json.dumps(SAMPLE))
        return path

    def test_a_file_is_read(self, custom):
        backend = DemoBackend.create(DemoBackendSettings(custom_data_path=custom))

        assert [entry.name for entry in backend.list_passwords()] == ["example/entry"]

    def test_a_directory_holding_one_is_read_too(self, custom, tmp_path):
        directory = tmp_path / "data"
        directory.mkdir()
        (directory / "demo.json").write_text(custom.read_text())

        backend = DemoBackend.create(DemoBackendSettings(custom_data_path=directory))

        assert [entry.name for entry in backend.list_passwords()] == ["example/entry"]

    def test_a_path_that_is_not_there_is_reported(self, tmp_path):
        """Rather than silently showing the built-in entries instead.

        Falling back looks like the setting worked and the file was empty, which
        is the one reading that is never true.
        """
        with pytest.raises(BackendError):
            DemoBackend.create(
                DemoBackendSettings(custom_data_path=tmp_path / "nowhere.json")
            )

    def test_a_file_that_is_not_json_is_reported(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{ this is not json")

        with pytest.raises(BackendError):
            DemoBackend.create(DemoBackendSettings(custom_data_path=broken))
