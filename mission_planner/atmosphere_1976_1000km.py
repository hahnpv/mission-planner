"""
1976 US Standard Atmosphere Model Extended to 1000 km

This module implements the 1976 US Standard Atmosphere extended to 1000 km altitude
with optimized look-up tables for fast queries. The model provides temperature,
pressure, density, speed of sound, molecular weight, and gravity as functions of
geometric altitude.

Extension to 1000 km uses tabulated data from the US Standard Atmosphere 1976
reference document with cubic interpolation for smooth property variation.

The atmosphere is divided into layers:
- 0-86 km: Lower atmosphere with analytical equations
- 86-1000 km: Upper atmosphere with tabulated data and cubic interpolation

1976 Gravity Model:
- Uses International Gravity Formula (IGF 1967)
- Accounts for latitude variation due to Earth's oblate shape
- Accounts for altitude variation using free-air correction
- Consistent with 1976 US Standard Atmosphere document

"""

import numpy as np
from scipy.interpolate import interp1d

G0 = 9.80665  # m/s^2, standard gravity


class Atmosphere1976_1000km:
    """
    1976 US Standard Atmosphere model extended to 1000 km with fast look-up tables.

    This class pre-computes atmospheric properties and gravity over a range of altitudes
    up to 1000 km and uses fast interpolation for queries. Designed for use in trajectory
    optimization where speed is critical.

    The model uses analytical equations from 0-86 km and tabulated data with cubic
    interpolation from 86-1000 km, exactly as specified in the 1976 reference document.

    Usage:
        atm = Atmosphere1976_1000km(latitude_deg=28.5)  # Cape Canaveral latitude
        T, P, rho, a, g, mw = atm.query(altitude_m)

    Parameters:
        latitude_deg (float): Geodetic latitude in degrees for gravity calculation, default=45.0
        h_min (float): Minimum altitude for look-up table (m), default=-1000
        h_max (float): Maximum altitude for look-up table (m), default=1000000
        n_points (int): Number of points in look-up table, default=20000

    Returns from query():
        T (ndarray): Temperature (K)
        P (ndarray): Pressure (Pa)
        rho (ndarray): Density (kg/m³)
        a (ndarray): Speed of sound (m/s)
        g (ndarray): Gravitational acceleration (m/s²)
        mw (ndarray): Molecular weight (kg/kmol)
    """

    # Physical constants
    R_STAR = 8314.32  # Universal gas constant (J/(kmol·K))
    gamma = 1.4  # Ratio of specific heats for air
    g0 = G0  # Standard gravity at sea level, 45° latitude (m/s²)

    # 1976 Gravity model constants (International Gravity Formula 1967)
    r_earth = 6356766.0  # Polar Earth radius (m)

    # Sea level conditions
    T0 = 288.15  # Sea level temperature (K)
    P0 = 101325.0  # Sea level pressure (Pa)
    rho0 = 1.225  # Sea level density (kg/m³)
    MW0 = 28.9644  # Sea level molecular weight (kg/kmol)

    # GMR constant for hydrostatic equation
    GMR = 1000.0 * g0 * MW0 / R_STAR  # = 34.163195 K/km

    # Layer boundaries for lower atmosphere (geopotential altitude in meters)
    # [base altitude, lapse rate K/m, base temp K, base pressure Pa]
    _layers = np.array(
        [
            [0.0, -0.0065, 288.15, 101325.0],  # Troposphere
            [11000.0, 0.0, 216.65, 22632.1],  # Tropopause
            [20000.0, 0.001, 216.65, 5474.89],  # Stratosphere 1
            [32000.0, 0.0028, 228.65, 868.019],  # Stratosphere 2
            [47000.0, 0.0, 270.65, 110.906],  # Stratopause
            [51000.0, -0.0028, 270.65, 66.9389],  # Mesosphere 1
            [71000.0, -0.002, 214.65, 3.95642],  # Mesosphere 2
            [84852.0, 0.0, 186.946, 0.3734],  # End of lower atmosphere
        ]
    )

    # Upper atmosphere tables (86-1000 km) from US Standard Atmosphere 1976
    # Altitude table (km converted to m)
    _Z_UPPER = (
        np.array(
            [
                86.0,
                93.0,
                100.0,
                107.0,
                114.0,
                121.0,
                128.0,
                135.0,
                142.0,
                150.0,
                160.0,
                170.0,
                180.0,
                190.0,
                200.0,
                220.0,
                260.0,
                300.0,
                400.0,
                500.0,
                600.0,
                700.0,
                800.0,
                900.0,
                1000.0,
            ]
        )
        * 1000.0
    )  # Convert to meters

    # Pressure ratio table (DELTA = P/P0)
    _DELTA_TABLE = np.array(
        [
            3.6850e-6,
            1.0660e-6,
            3.1593e-7,
            1.0611e-7,
            4.3892e-8,
            2.3095e-8,
            1.3997e-8,
            9.2345e-9,
            6.4440e-9,
            4.4828e-9,
            2.9997e-9,
            2.0933e-9,
            1.5072e-9,
            1.1118e-9,
            8.3628e-10,
            4.9494e-10,
            1.9634e-10,
            8.6557e-11,
            1.4328e-11,
            2.9840e-12,
            8.1056e-13,
            3.1491e-13,
            1.6813e-13,
            1.0731e-13,
            7.4155e-14,
        ]
    )

    # Density ratio table (SIGMA = RHO/RHO0)
    _SIGMA_TABLE = np.array(
        [
            5.680e-6,
            1.632e-6,
            4.575e-7,
            1.341e-7,
            4.061e-8,
            1.614e-8,
            7.932e-9,
            4.461e-9,
            2.741e-9,
            1.694e-9,
            1.007e-9,
            6.380e-10,
            4.240e-10,
            2.923e-10,
            2.074e-10,
            1.116e-10,
            3.871e-11,
            1.564e-11,
            2.288e-12,
            4.257e-13,
            9.279e-14,
            2.506e-14,
            9.272e-15,
            4.701e-15,
            2.907e-15,
        ]
    )

    # Molecular weight table (kg/kmol)
    _MW_TABLE = np.array(
        [
            28.95,
            28.82,
            28.40,
            27.64,
            26.79,
            26.12,
            25.58,
            25.09,
            24.62,
            24.10,
            23.49,
            22.90,
            22.34,
            21.81,
            21.30,
            20.37,
            18.85,
            17.73,
            15.98,
            14.33,
            11.51,
            8.00,
            5.54,
            4.40,
            3.94,
        ]
    )

    # Derivatives for cubic interpolation (per km from Fortran code)
    # These will be converted to per meter when used in _evaluate_cubic
    _DLOGDELTA = (
        np.array(
            [
                -0.174061,
                -0.177924,
                -0.167029,
                -0.142755,
                -0.107859,
                -0.079322,
                -0.064664,
                -0.054879,
                -0.048260,
                -0.042767,
                -0.037854,
                -0.034270,
                -0.031543,
                -0.029384,
                -0.027632,
                -0.024980,
                -0.021559,
                -0.019557,
                -0.016735,
                -0.014530,
                -0.011314,
                -0.007677,
                -0.005169,
                -0.003944,
                -0.003612,
            ]
        )
        / 1000.0
    )  # Convert from per km to per m

    _DLOGSIGMA = (
        np.array(
            [
                -0.172421,
                -0.182258,
                -0.178090,
                -0.176372,
                -0.154322,
                -0.113750,
                -0.090582,
                -0.075033,
                -0.064679,
                -0.056067,
                -0.048461,
                -0.043042,
                -0.038869,
                -0.035648,
                -0.033063,
                -0.029164,
                -0.024220,
                -0.021336,
                -0.017686,
                -0.016035,
                -0.014327,
                -0.011631,
                -0.008248,
                -0.005580,
                -0.004227,
            ]
        )
        / 1000.0
    )  # Convert from per km to per m

    _DMW = (
        np.array(
            [
                -0.001340,
                -0.036993,
                -0.086401,
                -0.123115,
                -0.111136,
                -0.083767,
                -0.072368,
                -0.068190,
                -0.066300,
                -0.063131,
                -0.059786,
                -0.057724,
                -0.054318,
                -0.052004,
                -0.049665,
                -0.043499,
                -0.032674,
                -0.023804,
                -0.014188,
                -0.021444,
                -0.034136,
                -0.031911,
                -0.017321,
                -0.006804,
                -0.003463,
            ]
        )
        / 1000.0
    )  # Convert from per km to per m

    def __init__(self, latitude_deg=45.0, h_min=-1000.0, h_max=1000000.0, n_points=20000):
        """
        Initialize the atmosphere model and build look-up tables.

        Args:
            latitude_deg: Geodetic latitude in degrees for gravity calculation
            h_min: Minimum altitude (m)
            h_max: Maximum altitude (m)
            n_points: Number of points in look-up table
        """
        self.latitude_deg = latitude_deg
        self.h_min = h_min
        self.h_max = h_max
        self.n_points = n_points

        # Build look-up tables
        self._build_tables()

    def _geopotential_altitude(self, h_geometric):
        """
        Convert geometric altitude to geopotential altitude.

        Args:
            h_geometric: Geometric altitude (m)

        Returns:
            Geopotential altitude (m)
        """
        return self.r_earth * h_geometric / (self.r_earth + h_geometric)

    def _kinetic_temperature(self, z_km):
        """
        Compute kinetic temperature above 86 km.

        Args:
            z_km: Geometric altitude (km)

        Returns:
            Temperature (K)
        """
        # Constants from Table 5 of US Standard Atmosphere 1976
        C1 = -76.3232
        C2 = 19.9429
        C3 = 12.0
        C4 = 0.01875
        TC = 263.1905
        T7 = 186.8673
        Z8 = 91.0
        Z9 = 110.0
        T9 = 240.0
        Z10 = 120.0
        T10 = 360.0
        T12 = 1000.0  # T_infinity

        r_earth_km = self.r_earth / 1000.0

        if z_km <= Z8:
            return T7
        elif z_km < Z9:
            xx = (z_km - Z8) / C2
            yy = np.sqrt(1.0 - xx * xx)
            return TC + C1 * yy
        elif z_km <= Z10:
            return T9 + C3 * (z_km - Z9)
        else:
            xx = (r_earth_km + Z10) / (r_earth_km + z_km)
            yy = (T12 - T10) * np.exp(-C4 * (z_km - Z10) * xx)
            return T12 - yy

    def _evaluate_cubic(self, a, fa, fpa, b, fb, fpb, u):
        """
        Evaluate cubic polynomial defined by function and derivative at two points.

        Args:
            a, fa, fpa: Point a, f(a), f'(a)
            b, fb, fpb: Point b, f(b), f'(b)
            u: Point where function is to be evaluated

        Returns:
            fu: Computed value of f(u)
        """
        d = (fb - fa) / (b - a)
        t = (u - a) / (b - a)
        p = 1.0 - t

        fu = p * fa + t * fb - p * t * (b - a) * (p * (d - fpa) - t * (d - fpb))
        return fu

    def _compute_lower_atmosphere(self, h_geometric):
        """
        Compute atmospheric properties for altitudes 0-86 km.

        Args:
            h_geometric: Geometric altitude (m), scalar

        Returns:
            T, P, rho, mw: Temperature (K), Pressure (Pa), Density (kg/m³),
                           Molecular weight (kg/kmol)
        """
        # Convert to geopotential altitude (in meters)
        h = self._geopotential_altitude(h_geometric)

        # Find the appropriate layer
        layer_idx = 0
        for j in range(len(self._layers) - 1):
            if h >= self._layers[j, 0]:
                layer_idx = j
            else:
                break

        # Get layer properties
        h_base = self._layers[layer_idx, 0]
        L = self._layers[layer_idx, 1]  # Lapse rate (K/m)
        T_base = self._layers[layer_idx, 2]
        P_base = self._layers[layer_idx, 3]

        # Calculate temperature
        if L == 0:  # Isothermal layer
            T = T_base
            # Pressure for isothermal layer
            # Convert GMR from K/km to K/m by dividing by 1000
            P = P_base * np.exp(-(self.GMR / 1000.0) * (h - h_base) / T_base)
        else:  # Gradient layer
            T = T_base + L * (h - h_base)
            # Pressure for gradient layer
            # GMR is in K/km, L is in K/m, so GMR/1000 gives K/m
            P = P_base * (T / T_base) ** (-(self.GMR / 1000.0) / L)

        # Calculate density from ideal gas law
        R_specific = self.R_STAR / self.MW0  # J/(kg·K)
        rho = P / (R_specific * T)

        # Molecular weight is constant below 86 km
        mw = self.MW0

        return T, P, rho, mw

    def _compute_upper_atmosphere(self, h_geometric):
        """
        Compute atmospheric properties for altitudes 86-1000 km.

        Args:
            h_geometric: Geometric altitude (m), scalar

        Returns:
            T, P, rho, mw: Temperature (K), Pressure (Pa), Density (kg/m³),
                           Molecular weight (kg/kmol)
        """
        # Clamp to maximum altitude
        if h_geometric > self._Z_UPPER[-1]:
            h_geometric = self._Z_UPPER[-1]

        # Find interpolation interval using binary search
        i = np.searchsorted(self._Z_UPPER, h_geometric) - 1
        i = max(0, min(i, len(self._Z_UPPER) - 2))

        # Cubic interpolation for log(delta) and log(sigma)
        logdelta = self._evaluate_cubic(
            self._Z_UPPER[i],
            np.log(self._DELTA_TABLE[i]),
            self._DLOGDELTA[i],
            self._Z_UPPER[i + 1],
            np.log(self._DELTA_TABLE[i + 1]),
            self._DLOGDELTA[i + 1],
            h_geometric,
        )

        logsigma = self._evaluate_cubic(
            self._Z_UPPER[i],
            np.log(self._SIGMA_TABLE[i]),
            self._DLOGSIGMA[i],
            self._Z_UPPER[i + 1],
            np.log(self._SIGMA_TABLE[i + 1]),
            self._DLOGSIGMA[i + 1],
            h_geometric,
        )

        # Cubic interpolation for molecular weight
        mw = self._evaluate_cubic(
            self._Z_UPPER[i],
            self._MW_TABLE[i],
            self._DMW[i],
            self._Z_UPPER[i + 1],
            self._MW_TABLE[i + 1],
            self._DMW[i + 1],
            h_geometric,
        )

        # Convert ratios to actual values
        delta = np.exp(logdelta)
        sigma = np.exp(logsigma)
        P = delta * self.P0
        rho = sigma * self.rho0

        # Kinetic temperature
        T = self._kinetic_temperature(h_geometric / 1000.0)

        return T, P, rho, mw

    def _compute_atmosphere(self, h_geometric):
        """
        Compute atmospheric properties at given geometric altitude.

        Args:
            h_geometric: Geometric altitude (m), can be scalar or array

        Returns:
            T, P, rho, a, mw: Temperature (K), Pressure (Pa), Density (kg/m³),
                              Speed of sound (m/s), Molecular weight (kg/kmol)
        """
        # Ensure array
        scalar_input = np.isscalar(h_geometric)
        h = np.atleast_1d(h_geometric)

        # Initialize outputs
        T = np.zeros_like(h)
        P = np.zeros_like(h)
        rho = np.zeros_like(h)
        mw = np.zeros_like(h)

        # Process each altitude
        for i, h_val in enumerate(h):
            if h_val <= 86000.0:
                T[i], P[i], rho[i], mw[i] = self._compute_lower_atmosphere(h_val)
            else:
                T[i], P[i], rho[i], mw[i] = self._compute_upper_atmosphere(h_val)

        # Calculate speed of sound
        R_specific = self.R_STAR / mw  # J/(kg·K)
        a = np.sqrt(self.gamma * R_specific * T)

        if scalar_input:
            return T[0], P[0], rho[0], a[0], mw[0]
        else:
            return T, P, rho, a, mw

    def _compute_1976_gravity(self, h_geometric, lat_deg):
        """
        Compute gravity using 1976 US Standard Atmosphere gravity model.

        Args:
            h_geometric: Geometric altitude above sea level (m)
            lat_deg: Geodetic latitude (degrees)

        Returns:
            g: Gravitational acceleration (m/s²)
        """
        # Convert latitude to radians
        lat_rad = np.deg2rad(lat_deg)

        # International Gravity Formula 1967
        cos2_lat = np.cos(2.0 * lat_rad)
        g_surface = G0 * (1.0 - 0.0026373 * cos2_lat + 0.0000059 * cos2_lat**2)

        # Free-air correction for altitude
        g_altitude = g_surface * (self.r_earth / (self.r_earth + h_geometric)) ** 2

        return g_altitude

    def _build_tables(self):
        """Build interpolation look-up tables for fast queries."""
        # Create altitude array
        self.h_table = np.linspace(self.h_min, self.h_max, self.n_points)

        # Compute atmospheric properties
        T_table, P_table, rho_table, a_table, mw_table = self._compute_atmosphere(self.h_table)

        # Compute 1976 gravity model at the specified latitude
        g_table = self._compute_1976_gravity(self.h_table, self.latitude_deg)

        # Store boundary values for clamping
        self._T_max = T_table[-1]
        self._P_max = P_table[-1]
        self._rho_max = rho_table[-1]
        self._a_max = a_table[-1]
        self._g_max = g_table[-1]
        self._mw_max = mw_table[-1]

        # Create interpolation functions (cubic for smoothness and speed)
        # Use fill_value tuple: (lower_bound_value, upper_bound_value)
        self._T_interp = interp1d(
            self.h_table,
            T_table,
            kind="cubic",
            bounds_error=False,
            fill_value=(T_table[0], self._T_max),
        )
        self._P_interp = interp1d(
            self.h_table,
            P_table,
            kind="cubic",
            bounds_error=False,
            fill_value=(P_table[0], self._P_max),
        )
        self._rho_interp = interp1d(
            self.h_table,
            rho_table,
            kind="cubic",
            bounds_error=False,
            fill_value=(rho_table[0], self._rho_max),
        )
        self._a_interp = interp1d(
            self.h_table,
            a_table,
            kind="cubic",
            bounds_error=False,
            fill_value=(a_table[0], self._a_max),
        )
        self._g_interp = interp1d(
            self.h_table,
            g_table,
            kind="cubic",
            bounds_error=False,
            fill_value=(g_table[0], self._g_max),
        )
        self._mw_interp = interp1d(
            self.h_table,
            mw_table,
            kind="cubic",
            bounds_error=False,
            fill_value=(mw_table[0], self._mw_max),
        )

    def query(self, h):
        """
        Query atmospheric properties and gravity at given altitude(s).

        This is the primary method for fast look-up of atmospheric properties.
        Uses pre-computed interpolation tables for maximum speed.

        Args:
            h: Geometric altitude (m), can be scalar or array

        Returns:
            T: Temperature (K)
            P: Pressure (Pa)
            rho: Density (kg/m³)
            a: Speed of sound (m/s)
            g: Gravitational acceleration (m/s²)
            mw: Molecular weight (kg/kmol)

        Example:
            >>> atm = Atmosphere1976_1000km(latitude_deg=28.5)
            >>> T, P, rho, a, g, mw = atm.query(100000.0)
            >>> print(f"At 100 km: T={T:.2f} K, P={P:.3e} Pa, mw={mw:.2f} kg/kmol")
        """
        T = self._T_interp(h)
        P = self._P_interp(h)
        rho = self._rho_interp(h)
        a = self._a_interp(h)
        g = self._g_interp(h)
        mw = self._mw_interp(h)

        return T, P, rho, a, g, mw

    def query_dict(self, h):
        """
        Query atmospheric properties and gravity, return as dictionary.

        Args:
            h: Geometric altitude (m), can be scalar or array

        Returns:
            Dictionary with keys: 'T', 'P', 'rho', 'a', 'g', 'mw'
        """
        T, P, rho, a, g, mw = self.query(h)
        return {"T": T, "P": P, "rho": rho, "a": a, "g": g, "mw": mw}

    def compute_exact(self, h):
        """
        Compute atmospheric properties using exact formula (no interpolation).

        This method is slower but more accurate. Useful for validation or
        when ultimate accuracy is needed.

        Args:
            h: Geometric altitude (m), can be scalar or array

        Returns:
            T, P, rho, a, g, mw: Temperature (K), Pressure (Pa), Density (kg/m³),
                                 Speed of sound (m/s), Gravity (m/s²),
                                 Molecular weight (kg/kmol)
        """
        T, P, rho, a, mw = self._compute_atmosphere(h)

        # Ensure h is array for gravity calculation
        h_array = np.atleast_1d(h)
        g = self._compute_1976_gravity(h_array, self.latitude_deg)

        # Return scalar if input was scalar
        if np.isscalar(h):
            return T, P, rho, a, float(g[0]), mw
        else:
            return T, P, rho, a, g, mw


# Module-level cache, keyed by latitude. Gravity is latitude-dependent, so a
# single global instance would silently return the FIRST caller's latitude for
# every subsequent call (M5). Building the 20k-point tables is expensive, so we
# cache per distinct latitude rather than rebuild every call.
_atm_cache = {}


def get_atmosphere(latitude_deg=45.0):
    """
    Get a cached atmosphere instance for the given latitude (lazy init).

    Args:
        latitude_deg: Geodetic latitude for gravity calculation (default 45.0)
    """
    key = round(float(latitude_deg), 6)
    atm = _atm_cache.get(key)
    if atm is None:
        atm = Atmosphere1976_1000km(latitude_deg=latitude_deg)
        _atm_cache[key] = atm
    return atm


if __name__ == "__main__":
    """Test and demonstrate the extended atmosphere model."""

    print("1976 US Standard Atmosphere Model Extended to 1000 km")
    print("=" * 80)

    # Create atmosphere instance at 45°N latitude
    atm = Atmosphere1976_1000km(latitude_deg=45.0)

    # Test altitudes from 0 to 1000 km
    test_altitudes_km = np.array(
        [
            0,
            10,
            20,
            30,
            40,
            50,
            60,
            70,
            80,
            90,
            100,
            150,
            200,
            300,
            400,
            500,
            600,
            700,
            800,
            900,
            1000,
        ]
    )
    test_altitudes = test_altitudes_km * 1000.0  # Convert to meters

    print(f"\nAtmosphere at Latitude: {atm.latitude_deg}°")
    print("\nAlt    Temp      Pressure    Density      Sound     Gravity    Mol.Wt.")
    print("(km)   (K)       (Pa)        (kg/m³)      (m/s)     (m/s²)     (kg/kmol)")
    print("-" * 85)

    for h_km, h in zip(test_altitudes_km, test_altitudes):
        T, P, rho, a, g, mw = atm.query(h)
        print(f"{h_km:4.0f}   {T:7.2f}   {P:10.3e}  {rho:10.3e}  {a:8.2f}  {g:9.6f}  {mw:7.3f}")

    # Performance test
    print("\n" + "=" * 80)
    print("Performance Test")
    print("=" * 80)

    import time

    # Test with array of altitudes
    h_test = np.linspace(0, 500000, 10000)

    # Time the interpolation method
    start = time.time()
    for _ in range(100):
        T, P, rho, a, g, mw = atm.query(h_test)
    end = time.time()
    print("\nInterpolation method (100 iterations, 10000 points each):")
    print(f"  Total time: {(end - start) * 1000:.2f} ms")
    print(f"  Time per query: {(end - start) * 10:.2f} ms")

    # Time the exact method (fewer iterations due to slowness)
    start = time.time()
    for _ in range(10):
        T, P, rho, a, g, mw = atm.compute_exact(h_test)
    end = time.time()
    print("\nExact method (10 iterations, 10000 points each):")
    print(f"  Total time: {(end - start) * 1000:.2f} ms")
    print(f"  Time per query: {(end - start) * 100:.2f} ms")
    print(f"\nSpeedup factor: ~{(end * 100 / start):.0f}x")

    print("\n" + "=" * 80)
    print("Tests Complete!")
    print("=" * 80)
