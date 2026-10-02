"""Image Generation Studio.

The version lives here and nowhere else. ``pyproject.toml`` reads it for the
package metadata and the user agent is built from it, so a release is one edit
here instead of three that can drift apart.
"""

from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["__version__"]
