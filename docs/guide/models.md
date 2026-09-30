# Models and assumptions

mission-planner is a **planning** tool: fast, transparent models that are
right to the level a first look needs, and plain about what they leave out.
Higher-fidelity propagators plug in as extra modes (see the
[Plugin guide](../plugins.md)).

## Earth, frames and time

- **A spherical Earth** of equatorial radius $R_E$ = 6378.137 km. Altitudes
  are above that sphere, and latitudes — sites and ground tracks alike — are
  **geocentric**. The gap to geodetic latitude is at most about 0.19°
  (≈ 0.17° at 30°).
- **Constants** follow WGS-84 / IERS: $\mu$ = 3.986004418 × 10¹⁴ m³/s²,
  $J_2$ = 1.08262668 × 10⁻³, $\omega_E$ = 7.2921159 × 10⁻⁵ rad/s.
- **Time** is UTC throughout; a naive datetime is taken as UTC. The Earth's
  orientation is Greenwich mean sidereal time (the IAU-1982 polynomial)
  advanced at the IERS rotation rate. Polar motion and UT1 − UTC (under a
  second) are ignored — under 0.005° of Earth rotation.

## Kepler + J2 (`kepler` mode)

Two-body motion with the **secular** effects of $J_2$: the node regresses,
perigee rotates and the mean motion shifts,

$$
\dot\Omega = -\tfrac32 n J_2 \left(\frac{R_E}{p}\right)^2 \cos i, \qquad
\dot\omega = \tfrac34 n J_2 \left(\frac{R_E}{p}\right)^2 (5\cos^2 i - 1),
$$

$$
\dot M = n\left[1 + \tfrac34 J_2 \left(\frac{R_E}{p}\right)^2 \sqrt{1-e^2}\,(3\cos^2 i - 1)\right],
$$

with $p = a(1-e^2)$. Short-period $J_2$ terms, higher harmonics, drag, the
Sun and Moon and solar pressure are **not** modelled, so this mode never
decays and its along-track error grows slowly with time — fine for days of
ground tracks and for repeat and sun-synchronous design.

Two periods are reported: `period_s`, the **anomalistic** period (perigee to
perigee), and `nodal_period_s`, the **nodal** period (node to node, which
adds the perigee drift). Ground-track repeats and `revs_per_day` use the
nodal one.

## Drag decay (`decay` mode)

An averaged King-Hele model for **near-circular** orbits ($e \le 0.05$):

$$
\frac{da}{dt} = -F\,\frac{\rho(h)\sqrt{\mu a}}{\beta}, \qquad
\beta = \frac{m}{C_D A}\ \ [\mathrm{kg/m^2}], \qquad
F = \left(1 - \frac{\omega_E\, a \cos i}{v}\right)^2
$$

$F$ accounts for the atmosphere rotating with the Earth: a prograde vehicle
meets less relative wind (about 0.92 at 400 km and 51.6°). The semi-major
axis, argument of latitude and node are integrated with RK4 — the $J_2$
rates re-evaluated as the orbit shrinks — with a step that refines only when
decay is fast, so weeks-long horizons stay cheap. The track stops at the
**100 km entry interface** and reports where and when it got there.

Density $\rho(h)$ is the **US Standard Atmosphere 1976**, extended to
1000 km and extrapolated log-linearly above that. It is a **static**
atmosphere: no solar cycle (F10.7), geomagnetic activity or day/night
bulge. Real thermospheric density swings by factors of a few over the solar
cycle, so decay lifetimes here are **nominal, not predictions**.

## Launch geometry

`from_launch_site` places the orbit plane over the site at the epoch: the
argument of latitude at the site comes from $\sin u = \sin\phi / \sin i$, and
the node from the site's inertial longitude. No inclination below the site's
latitude can pass over it. The launch azimuth is the inertial one,
$\sin A = \cos i / \cos\phi$, corrected for the eastward velocity of the
launch site at the orbital speed. There is no ascent: the vehicle is simply
in orbit over the site at t = 0.

## Sun-synchronous orbits

The sun-synchronous preset picks the inclination at which $J_2$ turns the
node once a year (+0.9856°/day) for the chosen altitudes, and sets the node
from the local time of ascending node against the **mean** sun. The equation
of time (up to about 16 minutes) is ignored. The repeat-ground-track
variants solve for an altitude with an exact whole number of revolutions per
solar day.

## Passes and visibility

- A **pass** is the sub-satellite point coming within a set ground distance
  (great circle on the sphere) of a target. It is geometry, not line of
  sight: it ignores altitude, terrain and elevation masks.
- The **horizon footprint** is the ground from which the vehicle is above the
  horizon (0° elevation) on the spherical Earth; the ground station uses the
  same geometry.
- Distances between samples are not interpolated: a pass is found at the
  track's sample spacing (30 s by default), so a very short graze of a small
  circle can fall between samples.

## Limits

A single plan is capped at 200,000 track samples in all (across every track
of a multi-track plan); the UI coarsens the step for long horizons to stay
near 20,000.
