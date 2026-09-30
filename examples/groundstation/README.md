# mission-planner-groundstation

A ground station for [mission-planner](https://github.com/hahnpv/mission-planner):
place a station on the map, set an elevation mask, and get the contact windows
(AOS / LOS, duration, maximum elevation, azimuths) and coverage of any plan —
in the UI panel, over REST and as the MCP tool `ground_contacts`.

It is also the worked example of the plugin tutorial:
<https://hahnpv.github.io/mission-planner/tutorial/>.

It is installed with mission-planner itself: the core's `pyproject.toml`
ships `mp_groundstation` and its entry point, so don't install this directory
separately (the plugin would be listed twice, the second as a duplicate).
This `pyproject.toml` is the template for packaging a plugin of your own.

```bash
pip install -e .                             # from the mission-planner checkout
python -m mission_planner.server             # the "ground station" panel appears
python -m pytest -q examples/groundstation   # its tests
```
