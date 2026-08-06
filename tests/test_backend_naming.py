"""Display names for configured backend instances.

The settings dialog has always had a name entry, but nothing ever wrote its
contents anywhere, so a rename was lost the moment the dialog closed and the
sidebar kept showing a name derived from the instance id.
"""

import pytest

from gtkpass.config import (
    get_backend_display_name,
    get_backend_settings,
    set_backend_display_name,
)


@pytest.fixture
def backend_id(request):
    """A unique instance id, reset to defaults afterwards."""
    identifier = f"demo_{abs(hash(request.node.name)) % 10**8}"
    yield identifier
    settings = get_backend_settings("demo", identifier)
    for key in settings.list_keys():
        settings.reset(key)


class TestPersistence:
    def test_a_name_survives_a_round_trip(self, backend_id):
        set_backend_display_name("demo", backend_id, "Work Laptop")

        assert get_backend_display_name("demo", backend_id) == "Work Laptop"

    def test_a_name_is_stored_per_instance(self, backend_id):
        other = backend_id + "_other"
        set_backend_display_name("demo", backend_id, "First")
        set_backend_display_name("demo", other, "Second")

        assert get_backend_display_name("demo", backend_id) == "First"
        assert get_backend_display_name("demo", other) == "Second"

        settings = get_backend_settings("demo", other)
        for key in settings.list_keys():
            settings.reset(key)

    def test_surrounding_whitespace_is_dropped(self, backend_id):
        set_backend_display_name("demo", backend_id, "  Padded  ")

        assert get_backend_display_name("demo", backend_id) == "Padded"

    def test_clearing_falls_back_to_the_derived_name(self, backend_id):
        set_backend_display_name("demo", backend_id, "Temporary")

        set_backend_display_name("demo", backend_id, "")

        assert get_backend_display_name("demo", backend_id) == "Demo"


class TestDerivedNames:
    """What is shown before the user has named anything."""

    def test_a_generated_id_yields_the_backend_type(self):
        assert get_backend_display_name("demo", "demo_1766234611") == "Demo"

    def test_known_types_get_a_readable_label(self):
        assert get_backend_display_name("secretservice", "secretservice_1") == (
            "Secret Service"
        )

    def test_a_custom_id_is_humanised(self):
        assert get_backend_display_name("demo", "my_test_backend") == "My Test Backend"
