"""A GTK4/Libadwaita frontend for pluggable password backends.

Importing this requires GTKPass to have been installed -- see
:func:`gtkpass.safety.require_installed` for why running from a bare source
tree is refused rather than tolerated.
"""

from gtkpass.safety import require_installed

require_installed()
