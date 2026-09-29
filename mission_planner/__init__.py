"""mission_planner — generic orbital mission planning.

Library:  Orbit, LaunchSite/SITES, GroundTrack, Scene
Web UI:   python -m mission_planner.server   (http://127.0.0.1:3030)
MCP:      python -m mission_planner.mcp_server
"""

from importlib.metadata import PackageNotFoundError, version

from .constants import J2, MU, OMEGA_E, RE
from .groundtrack import GroundTrack
from .launch_site import SITES, LaunchSite, launch_azimuth
from .orbit import Orbit
from .scene import Scene

try:
    __version__ = version("mission-planner")
except PackageNotFoundError:  # running from a checkout without an install
    __version__ = "0+unknown"

__all__ = [
    "__version__",
    "Orbit",
    "GroundTrack",
    "LaunchSite",
    "SITES",
    "launch_azimuth",
    "Scene",
    "RE",
    "MU",
    "J2",
    "OMEGA_E",
]
