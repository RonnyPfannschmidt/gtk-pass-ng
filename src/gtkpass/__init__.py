"""A GTK4/Libadwaita frontend for pluggable password backends.

Importing this requires GTKPass to have been installed -- see
:func:`gtkpass.safety.require_installed` for why running from a bare source
tree is refused rather than tolerated.

It is also the last point before ``gi.repository`` is reachable, so a frozen
bundle arranges its environment here: GLib caches its schema source the first
time it is asked, and everything that asks is downstream of this import.
"""

from gtkpass.frozen import configure_environment
from gtkpass.safety import require_installed

configure_environment()
require_installed()
