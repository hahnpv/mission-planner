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

King-Hele's theory of satellite orbits in an atmosphere (*Theory of
Satellite Orbits in an Atmosphere*, 1964), for orbits with $e \le 0.2$.
Drag is averaged over one revolution in an atmosphere whose density falls
exponentially above perigee, $\rho = \rho_p\, e^{-(r - r_p)/H}$. With
$c = ae/H$ and $I_n = I_n(c)$ the modified Bessel functions, the changes per
revolution are

$$
\Delta a = -2\pi\delta a^2 \rho_p e^{-c}\left[I_0 + 2eI_1 + \tfrac34 e^2(I_0 + I_2)
+ \tfrac14 e^3(3I_1 + I_3)\right]
$$

$$
\Delta e = -2\pi\delta a \rho_p e^{-c}\left[I_1 + \tfrac{e}{2}(I_0 + I_2)
- \tfrac{e^2}{8}(5I_1 - I_3) - \tfrac{e^3}{16}(5I_0 + 4I_2 - I_4)\right]
$$

$$
\delta = \frac{F}{\beta}, \qquad
\beta = \frac{m}{C_D A}\ \ [\mathrm{kg/m^2}], \qquad
F = \left(1 - \frac{\omega_E\, r_p \cos i}{v_p}\right)^2
$$

The series is King-Hele's expansion in $e$, good to 0.1 % at $e = 0.2$; at
$e = 0$ it is the circular law $\dot a = -F\rho\sqrt{\mu a}/\beta$. $F$
accounts for the atmosphere rotating with the Earth: a prograde vehicle
meets less relative wind (about 0.92 at 400 km and 51.6°). Drag acts mostly
at perigee, so an elliptic orbit keeps its perigee roughly in place while
its apogee comes down; it circularizes, then decays like a circular orbit.

$\rho_p$ is the table density at perigee. The real scale height grows with
altitude, which King-Hele allows for by evaluating $H$ above perigee: here
$H$ is the table's local scale height **one scale height above perigee**, a
choice calibrated against a direct integration of the equations of motion
(two-body + drag in the same rotating atmosphere), which the averaged rates
match to about 3 % for $e$ up to 0.2.

The mean elements $a$, $e$, $M$, $\omega$, $\Omega$ are integrated with RK4 —
the $J_2$ rates re-evaluated as the orbit shrinks — with a step that refines
only when decay is fast, so weeks-long horizons stay cheap. The track is the
position on the ellipse of those elements, so its altitude swings between
perigee and apogee. It stops when **perigee reaches the 100 km entry
interface** and reports where and when; the decay profile carries the mean,
perigee and apogee altitudes. The samples fall at the Kepler track's times
for the same horizon and step, so switching modes doesn't move them. An
orbit whose perigee already lies below the interface is refused.

Density $\rho(h)$ is the **US Standard Atmosphere 1976**, extended to
1000 km and extrapolated log-linearly above that (a scale height of about
240 km). It is a **static**
atmosphere: no solar cycle (F10.7), geomagnetic activity or day/night
bulge. Real thermospheric density swings by factors of a few over the solar
cycle, so decay lifetimes here are **nominal, not predictions**.

## Launch geometry

`from_launch_site` places the orbit plane over the site at the epoch: the
argument of latitude at the site comes from $\sin u = \sin\phi / \sin i$, and
the node from the site's inertial longitude. Only inclinations with
$|\phi| \le i \le 180° - |\phi|$ can pass over the site. The launch azimuth
is the inertial one, $\sin A = \cos i / \cos\phi$, corrected for the eastward
velocity of the launch site at the orbital speed. There is no ascent: the
vehicle is simply in orbit over the site at t = 0.

## Manoeuvre budgets

The maneuver planner is impulsive and **circular-to-circular**: every burn
is instantaneous, every orbit before and after is circular, and all of it
is two-body (no J2, no drag, no finite-burn losses). With $v_c = \sqrt{\mu/r}$:

- **Hohmann** between radii $r_1$ and $r_2$: the transfer ellipse has
  $a_t = (r_1 + r_2)/2$ and vis-viva speeds $v_t = \sqrt{\mu(2/r - 1/a_t)}$
  at each end; $\Delta v_1 = |v_{t1} - v_{c1}|$, $\Delta v_2 = |v_{c2} - v_{t2}|$,
  transfer time half the ellipse's period.
- **Plane change** by $\Delta i$ alone, at circular speed:
  $\Delta v = 2 v_c \sin(\Delta i / 2)$. **Combined**, the rotation is folded
  into the Hohmann burn at the larger radius (where speed is lowest) by the
  law of cosines, $\Delta v = \sqrt{v_c^2 + v_t^2 - 2 v_c v_t \cos\Delta i}$,
  with the other burn coplanar.
- **Phasing** a target `lead_deg` ahead (positive) or behind: one revolution
  on an ellipse whose period is the circular one scaled by
  $1 - \text{lead}/360°$, entered and left with equal burns; the result
  carries the other apsis altitude and is flagged infeasible when that
  perigee dips below 120 km.
- **Deorbit** from the target orbit: the retro burn that drops perigee to
  the 100 km interface, $\Delta v = v_c - v_{apo}$ on the ellipse with
  $a = (r + r_{100})/2$, and the half-period coast to it.

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
  horizon (0° elevation) on the spherical Earth. The ground-station plugin
  uses the same geometry with an **elevation mask**: from the central angle
  $\psi$ between station and subpoint and the vehicle's radius $r$, the
  elevation is $\operatorname{atan2}(\cos\psi - R_E/r,\ \sin\psi)$; the
  station sits on the sphere (no station altitude, terrain or refraction).
- Distances between samples are not interpolated: a pass is found at the
  track's sample spacing (30 s by default), so a very short graze of a small
  circle can fall between samples.

## Limits

A single plan is capped at 200,000 track samples in all (across every track
of a multi-track plan); the UI coarsens the step for long horizons to stay
near 20,000.
