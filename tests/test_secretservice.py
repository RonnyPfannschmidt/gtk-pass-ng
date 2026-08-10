"""The keyring backend, against a stand-in collection.

There is no Secret Service on the private bus the suite runs under, and there
must never be one on the developer's: it holds their real secrets. So the
backend is built around a fake collection instead, which is enough for
everything that is not the D-Bus call itself -- and this is a backend that had
no tests at all.

The listing was written to show every item in the keyring, deliberately, while
reading filtered on `application=gtkpass`. So the sidebar offered entries that
answered "not found" when they were selected.
"""

import pytest

from gtkpass.backends.secretservice import SecretServiceBackend

#: What a foreign item's attributes look like: lookup keys its owner finds it
#: by, which are not GTKPass's to rewrite.
CHROMIUM = {
    "application": "chromium",
    "signon_realm": "https://example.com/",
    "username_value": "someone",
}


class FakeItem:
    def __init__(self, label, attributes, secret=b"", modified=0):
        self.collection = None
        self._label = label
        self._attributes = dict(attributes)
        self._secret = secret
        self._modified = modified

    def get_label(self):
        return self._label

    def set_label(self, label):
        self._label = label

    def get_attributes(self):
        return dict(self._attributes)

    def set_attributes(self, attributes):
        self._attributes = dict(attributes)

    def get_secret(self):
        return self._secret

    def set_secret(self, secret):
        self._secret = secret

    def get_modified(self):
        return self._modified

    def delete(self):
        assert self.collection is not None, "this item is in no collection"
        self.collection.items.remove(self)


class FakeCollection:
    def __init__(self, items=()):
        self.items = []
        for item in items:
            self.add(item)

    def add(self, item):
        item.collection = self
        self.items.append(item)
        return item

    def get_all_items(self):
        return list(self.items)

    def create_item(self, label, attributes, secret, replace=False):
        return self.add(FakeItem(label, attributes, secret))


@pytest.fixture
def ours():
    return FakeItem(
        "email/work",
        {"application": "gtkpass", "name": "email/work", "username": "alice"},
        b"hunter2",
    )


@pytest.fixture
def theirs():
    return FakeItem("example.com login", CHROMIUM, b"their-password")


@pytest.fixture
def backend(ours, theirs):
    return SecretServiceBackend(
        connection=None, collection=FakeCollection([ours, theirs])
    )


class TestListing:
    def test_it_shows_the_whole_keyring(self, backend):
        names = {entry.name for entry in backend.list_passwords()}

        assert names == {"email/work", "example.com login"}


class TestAnythingListedCanBeOpened:
    """Listing everything and reading only our own is not a coherent pair.

    Selecting a row the sidebar offered used to raise FileNotFoundError, which
    the window turns into "could not open" -- for an entry that is right there.
    """

    def test_an_item_gtkpass_wrote_is_read(self, backend):
        assert backend.get_password("email/work").password == "hunter2"

    def test_an_item_another_application_wrote_is_read_too(self, backend):
        assert backend.get_password("example.com login").password == "their-password"

    def test_something_that_is_not_there_is_still_reported(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.get_password("no/such/entry")


class TestEditingLeavesOtherApplicationsAlone:
    """An item's attributes are how its owner finds it again.

    Replacing them with GTKPass's own parsed set would leave a Chromium or
    NetworkManager entry in the keyring that its owner can no longer look up --
    silently, and long after the edit.
    """

    def test_the_owning_application_is_not_taken_over(self, backend, theirs):
        backend.edit_password("example.com login", "new-password\n")

        assert theirs.get_attributes()["application"] == "chromium"

    def test_the_lookup_attributes_survive(self, backend, theirs):
        backend.edit_password("example.com login", "new-password\n")

        assert theirs.get_attributes()["signon_realm"] == CHROMIUM["signon_realm"]
        assert theirs.get_attributes()["username_value"] == "someone"

    def test_the_secret_is_what_changed(self, backend, theirs):
        backend.edit_password("example.com login", "new-password\nnote: hello\n")

        assert theirs.get_secret() == b"new-password"

    def test_our_own_metadata_still_round_trips(self, backend, ours):
        backend.edit_password("email/work", "hunter3\nusername: bob\n")

        assert ours.get_secret() == b"hunter3"
        assert ours.get_attributes()["username"] == "bob"


class TestDeleting:
    def test_an_item_can_be_removed(self, backend, ours):
        backend.delete_password("email/work")

        assert [entry.name for entry in backend.list_passwords()] == [
            "example.com login"
        ]

    def test_removing_something_absent_is_reported(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.delete_password("no/such/entry")
