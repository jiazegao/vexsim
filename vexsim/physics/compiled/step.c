/* The physics step, compiled: a copy of the Python step's arithmetic.
 *
 * The model is the Python: Robot._step_python (robot.py) with V5Motor.update (motor.py),
 * MotorThermal (thermal.py), Mechanism.advance (mechanism.py), the contact functions
 * (wheel.py), NormalLoads (chassis.py), PowerSystem.end_step (power.py) and Battery
 * (battery.py). Each function here names the one it copies and keeps its expressions in the
 * same order, so the two give the same numbers to rounding. A change to the model is made
 * there first, then here; tests/test_step.py steps both from the same states, and
 * VEXSIM_STEP=check runs both on every step of anything (PLAN.md section 18).
 *
 * A robot's numbers live in one block of doubles (step_layout.h, written from the tables in
 * layout.py) that is read and written here in place; its NumPy arrays are reached by
 * pointer. Walls, game elements and sensors stay in Python.
 *
 * Plain C with no library but the C one, so the gcc beside the g++ vexsim finds builds it
 * and ctypes loads it, whatever compiler built Python. No -ffast-math, and no contraction
 * of a*b+c into one instruction: the Python doesn't.
 */

#include <math.h>

#include "step_layout.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

#define CHANNELS 3 /* a wheel's slip, free and rolling channels (wheel.py) */
#define MAX_ROWS (CHANNELS * VEXSIM_MAX_WHEELS)

/* Python's max(a, b) and min(a, b): the first, unless the second is strictly more (less) */
static double py_max(double a, double b) { return b > a ? b : a; }
static double py_min(double a, double b) { return b < a ? b : a; }

/* Python's a // b for floats (CPython's float_floor_div) */
static double py_floordiv(double vx, double wx) {
	double mod = fmod(vx, wx);
	double div = (vx - mod) / wx;
	if (mod != 0.0 && (wx < 0) != (mod < 0)) div -= 1.0;
	if (div != 0.0) {
		double floordiv = floor(div);
		if (div - floordiv > 0.5) floordiv += 1.0;
		return floordiv;
	}
	return copysign(0.0, vx / wx);
}

/* --- motor.py, thermal.py ---------------------------------------------------------------- */

/* CoreConstants.friction */
static double core_friction(const double *m, double w_core) {
	return m[M_COULOMB_NM] * tanh(w_core / m[M_SMOOTHING_RAD_S]) + m[M_VISCOUS_NM_S] * w_core;
}

/* MotorThermal.derate_factor */
static double derate_factor(const double *m) {
	static const double factors[] = {1.0, 0.5, 0.25, 0.125, 0.0};
	double over = m[M_HOUSING_C] - m[M_DERATE_START_C];
	double steps;
	if (over < 0) return factors[0];
	steps = py_floordiv(over, m[M_DERATE_STEP_C]);
	return factors[steps < 3.0 ? 1 + (int)steps : 4];
}

/* MotorThermal.step */
static void thermal_step(double *m, double heat_w, double dt) {
	double to_housing = (m[M_WINDING_C] - m[M_HOUSING_C]) / m[M_WINDING_TO_HOUSING_K_PER_W];
	double to_ambient = (m[M_HOUSING_C] - m[M_AMBIENT_C]) / m[M_HOUSING_TO_AMBIENT_K_PER_W];
	m[M_WINDING_C] += (heat_w - to_housing) * dt / m[M_WINDING_HEAT_CAPACITY_J_PER_K];
	m[M_HOUSING_C] += (to_housing - to_ambient) * dt / m[M_HOUSING_HEAT_CAPACITY_J_PER_K];
}

/* V5Motor._position_loop */
static double position_loop(const double *m, double target, double max_speed) {
	double speed = m[M_POSITION_KP] * (target - m[M_POSITION]);
	return py_min(py_max(speed, -max_speed), max_speed);
}

/* V5Motor._velocity_loop */
static double velocity_loop(double *m, double target, double v_bus, double dt) {
	double ke_out = m[M_KE] * m[M_RATIO];
	double error = target - m[M_VELOCITY_EST];
	double w_target_core = target * m[M_RATIO];
	double feedforward =
		m[M_KE] * w_target_core + m[M_RESISTANCE_OHM] * core_friction(m, w_target_core) / m[M_KT];
	double command = feedforward + m[M_VELOCITY_KP] * ke_out * error + m[M_INTEGRAL_V];

	int settling = fabs(m[M_ACCEL_EST]) > m[M_INTEGRAL_GATE] * m[M_RATED_SPEED];
	int voltage_pinned = fabs(command) >= v_bus && command * error > 0;
	int current_pinned = m[M_CURRENT_LIMITED] != 0.0 && m[M_CURRENT] * error > 0;
	if (!(settling || voltage_pinned || current_pinned)) {
		m[M_INTEGRAL_V] += m[M_VELOCITY_KI] * ke_out * error * dt;
		m[M_INTEGRAL_V] = py_min(py_max(m[M_INTEGRAL_V], -v_bus), v_bus);
	}
	return command;
}

/* V5Motor._drive_voltage */
static double drive_voltage(double *m, double v_bus, double dt) {
	int mode = (int)m[M_MODE];
	if (mode == MODE_VOLTAGE) {
		double cap = m[M_VOLTAGE_CAP], held;
		if (cap <= 0) return m[M_VOLTAGE_CMD];
		held = velocity_loop(m, copysign(cap * m[M_RATED_SPEED], m[M_VOLTAGE_CMD]), v_bus, dt);
		return copysign(py_min(fabs(m[M_VOLTAGE_CMD]), fabs(held)), m[M_VOLTAGE_CMD]);
	}
	if (mode == MODE_VELOCITY) return velocity_loop(m, m[M_VELOCITY_CMD], v_bus, dt);
	if (mode == MODE_POSITION)
		return velocity_loop(m, position_loop(m, m[M_POSITION_CMD], m[M_MAX_SPEED]), v_bus, dt);
	if ((int)m[M_BRAKE_MODE] == BRAKE_HOLD)
		return velocity_loop(m, position_loop(m, m[M_HOLD_TARGET], m[M_RATED_SPEED]), v_bus, dt);
	return 0.0; /* BRAKE: windings shorted */
}

/* V5Motor.update: one step with the output shaft at omega; the torque at the output.
 * The supply is the robot's: its bus voltage read, the motor's draw added to its load. */
static double motor_update(double *m, double *b, double omega, double dt) {
	double previous_est, w_core, v_bus, volts, current;
	int limited = 0;

	m[M_VELOCITY] = omega;
	m[M_POSITION] += omega * dt;
	previous_est = m[M_VELOCITY_EST];
	m[M_VELOCITY_EST] += (omega - m[M_VELOCITY_EST]) * (1.0 - exp(-dt / m[M_VELOCITY_FILTER_S]));
	m[M_ACCEL_EST] = (m[M_VELOCITY_EST] - previous_est) / dt;

	w_core = omega * m[M_RATIO];
	v_bus = py_max(b[R_BUS_VOLTAGE], 0.0);
	if ((int)m[M_MODE] == MODE_STOPPED && (int)m[M_BRAKE_MODE] == BRAKE_COAST) {
		volts = 0.0, current = 0.0;
	} else {
		double i_limit;
		volts = py_min(py_max(drive_voltage(m, v_bus, dt), -v_bus), v_bus);
		current = (volts - m[M_KE] * w_core) / m[M_RESISTANCE_OHM];
		/* V5Motor.effective_current_limit_a */
		i_limit = py_min(m[M_CURRENT_LIMIT], m[M_SUPPLY_CURRENT_CAP]) * derate_factor(m);
		if (fabs(current) > i_limit) {
			current = copysign(i_limit, current);
			volts = current * m[M_RESISTANCE_OHM] + m[M_KE] * w_core;
			limited = 1;
		}
	}

	m[M_TORQUE] = m[M_RATIO] * (m[M_KT] * current - core_friction(m, w_core));
	m[M_CURRENT] = current, m[M_VOLTAGE] = volts, m[M_CURRENT_LIMITED] = limited;
	m[M_POWER_IN] = volts * current;
	b[R_LOAD_W] += m[M_POWER_IN]; /* supply.add_load */
	thermal_step(m, current * current * m[M_RESISTANCE_OHM], dt);
	return m[M_TORQUE];
}

/* --- mechanism.py -------------------------------------------------------------------------- */

/* Mechanism.advance */
static void mechanism_advance(double *k, double *motors, double *b, double dt) {
	double w = k[K_SPEED], torque = 0.0, w_free, grip, angle;
	int first = (int)k[K_FIRST_MOTOR], count = (int)k[K_MOTOR_COUNT], i;

	for (i = 0; i < count; i++) {
		double *m = motors + (first + i) * M_SIZE;
		torque += m[M_SIGN] * motor_update(m, b, m[M_SIGN] * w, dt);
	}
	w_free = w + dt * (torque - k[K_LOAD]) / k[K_INERTIA];
	grip = dt * k[K_FRICTION] / k[K_INERTIA]; /* the most friction can change the speed */
	w = fabs(w_free) <= grip ? 0.0 : w_free - copysign(grip, w_free);
	angle = k[K_ANGLE] + w * dt;
	if (angle >= k[K_HIGH]) {
		angle = k[K_HIGH], w = py_min(w, 0.0);
	} else if (angle <= k[K_LOW]) {
		angle = k[K_LOW], w = py_max(w, 0.0);
	}
	k[K_ANGLE] = angle, k[K_SPEED] = w;
	for (i = 0; i < count; i++) { /* the encoders follow the output, stops included */
		double *m = motors + (first + i) * M_SIZE;
		m[M_POSITION] = m[M_SIGN] * angle;
	}
}

/* --- chassis.py: the wheels' loads ------------------------------------------------------- */

/* The least-squares solution of least norm of a symmetric 3x3 system, as
 * numpy.linalg.lstsq(system, rhs, rcond=None) gives it: by the system's eigenvectors
 * (Jacobi rotations), leaving out those whose eigenvalue is nothing beside the largest. */
static void solve_plane(double s[3][3], const double rhs[3], double plane[3]) {
	double v[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
	double largest = 0.0, cutoff;
	int sweep, p, q, i;

	for (sweep = 0; sweep < 60; sweep++) {
		double off = fabs(s[0][1]) + fabs(s[0][2]) + fabs(s[1][2]);
		double size = fabs(s[0][0]) + fabs(s[1][1]) + fabs(s[2][2]);
		if (off <= 1e-300 || off <= 1e-17 * size) break;
		for (p = 0; p < 2; p++) {
			for (q = p + 1; q < 3; q++) {
				double theta, t, c, sn;
				if (s[p][q] == 0.0) continue;
				theta = (s[q][q] - s[p][p]) / (2.0 * s[p][q]);
				t = (theta >= 0 ? 1.0 : -1.0) / (fabs(theta) + sqrt(theta * theta + 1.0));
				c = 1.0 / sqrt(t * t + 1.0), sn = t * c;
				for (i = 0; i < 3; i++) { /* columns p and q */
					double sp = s[i][p], sq = s[i][q];
					s[i][p] = c * sp - sn * sq, s[i][q] = sn * sp + c * sq;
				}
				for (i = 0; i < 3; i++) { /* rows p and q */
					double sp = s[p][i], sq = s[q][i];
					s[p][i] = c * sp - sn * sq, s[q][i] = sn * sp + c * sq;
				}
				for (i = 0; i < 3; i++) {
					double vp = v[i][p], vq = v[i][q];
					v[i][p] = c * vp - sn * vq, v[i][q] = sn * vp + c * vq;
				}
			}
		}
	}
	for (i = 0; i < 3; i++) largest = py_max(largest, fabs(s[i][i]));
	cutoff = 3.0 * 2.220446049250313e-16 * largest; /* rcond=None: eps times the larger side */
	plane[0] = plane[1] = plane[2] = 0.0;
	for (i = 0; i < 3; i++) {
		double along;
		if (fabs(s[i][i]) <= cutoff) continue;
		along = (v[0][i] * rhs[0] + v[1][i] * rhs[1] + v[2][i] * rhs[2]) / s[i][i];
		plane[0] += along * v[0][i], plane[1] += along * v[1][i], plane[2] += along * v[2][i];
	}
}

/* NormalLoads._solve_active, then its loads(rhs): the chassis plane on the wheels that touch */
static void active_loads(
	int W, const double *wheel, double stiffness, const int *active, const double rhs[3], double *loads
) {
	const double *pos_x = wheel + W_POS_X * W, *pos_y = wheel + W_POS_Y * W, *drop = wheel + W_DROP * W;
	double system[3][3] = {{0}}, offset[3] = {0}, right[3], plane[3];
	int i, r, c;

	for (i = 0; i < W; i++) {
		double basis[3];
		if (!active[i]) continue;
		basis[0] = 1.0, basis[1] = pos_x[i], basis[2] = pos_y[i];
		for (r = 0; r < 3; r++) {
			for (c = 0; c < 3; c++) system[r][c] += stiffness * basis[r] * basis[c];
			offset[r] += stiffness * basis[r] * drop[i];
		}
	}
	for (r = 0; r < 3; r++) right[r] = rhs[r] - offset[r];
	solve_plane(system, right, plane);
	for (i = 0; i < W; i++) {
		/* compression of wheel i: a + b*x_i + c*y_i + drop_i; its load, k times that */
		double height = plane[0] + pos_x[i] * plane[1] + pos_y[i] * plane[2];
		loads[i] = active[i] ? stiffness * (height + drop[i]) : 0.0;
	}
}

/* NormalLoads.__call__, with its _lift_off */
static void normal_loads(int W, const double *wheel, const double *b, double fx, double fy, double *loads) {
	const double *base = wheel + W_BASE * W, *sens_x = wheel + W_SENS_X * W, *sens_y = wheel + W_SENS_Y * W;
	double least = INFINITY, rhs[3], total = 0.0;
	int active[VEXSIM_MAX_WHEELS], i, pass;

	for (i = 0; i < W; i++) {
		loads[i] = base[i] + (sens_x[i] * fx + sens_y[i] * fy);
		least = py_min(least, loads[i]);
	}
	if (least >= 0.0) return; /* every wheel on the floor (the usual case) */

	rhs[0] = b[R_WEIGHT], rhs[1] = -b[R_CG_HEIGHT] * fx, rhs[2] = -b[R_CG_HEIGHT] * fy;
	for (i = 0; i < W; i++) active[i] = 1, loads[i] = 0.0;
	for (pass = 0; pass < W; pass++) {
		int lifted = 0;
		active_loads(W, wheel, b[R_STIFFNESS], active, rhs, loads);
		for (i = 0; i < W; i++) {
			if (active[i] && loads[i] < 0.0) active[i] = 0, lifted = 1;
		}
		if (!lifted) break;
	}
	for (i = 0; i < W; i++) {
		loads[i] = py_max(loads[i], 0.0);
		total += loads[i];
	}
	/* Past the tipping point no plane balances the moments; keep the total weight right. */
	if (total <= 0) {
		for (i = 0; i < W; i++) loads[i] = b[R_WEIGHT] / W;
	} else {
		for (i = 0; i < W; i++) loads[i] = loads[i] * (b[R_WEIGHT] / total);
	}
}

/* --- wheel.py ------------------------------------------------------------------------------ */

/* friction_circle: a traction wheel's slip and free forces, and their 2x2 Jacobian */
static void friction_circle(
	double slip, double free, double limit, double scale, double *f_slip, double *f_free, double *d_ss,
	double *d_ff, double *d_sf
) {
	double speed = hypot(slip, free), t, along, across, ux, uy;
	if (speed < 1e-9 * scale) {
		*f_slip = limit * slip / scale, *f_free = limit * free / scale;
		*d_ss = limit / scale, *d_ff = limit / scale, *d_sf = 0.0;
		return;
	}
	t = tanh(speed / scale);
	along = limit * (1.0 - t * t) / scale; /* d|F| / d|c| */
	across = limit * t / speed;            /* |F| / |c| */
	ux = slip / speed, uy = free / speed;
	*f_slip = across * slip, *f_free = across * free;
	*d_ss = across + (along - across) * ux * ux;
	*d_ff = across + (along - across) * uy * uy;
	*d_sf = (along - across) * ux * uy;
}

/* --- robot.py: the step --------------------------------------------------------------------- */

/* A x = rhs by elimination with row pivoting, as numpy.linalg.solve does; x comes back in
 * rhs. 1 when the system is singular. */
static int solve(int n, double *A, double *rhs) {
	int col, row, c;
	for (col = 0; col < n; col++) {
		int pivot = col;
		double best = fabs(A[col * n + col]), scale;
		for (row = col + 1; row < n; row++) {
			if (fabs(A[row * n + col]) > best) best = fabs(A[row * n + col]), pivot = row;
		}
		if (best == 0.0) return 1;
		if (pivot != col) {
			double swap;
			for (c = 0; c < n; c++) {
				swap = A[col * n + c], A[col * n + c] = A[pivot * n + c], A[pivot * n + c] = swap;
			}
			swap = rhs[col], rhs[col] = rhs[pivot], rhs[pivot] = swap;
		}
		scale = 1.0 / A[col * n + col];
		for (row = col + 1; row < n; row++) {
			double factor = A[row * n + col] * scale;
			if (factor == 0.0) continue;
			for (c = col + 1; c < n; c++) A[row * n + c] -= factor * A[col * n + c];
			rhs[row] -= factor * rhs[col];
		}
	}
	for (row = n - 1; row >= 0; row--) {
		double sum = rhs[row];
		for (c = row + 1; c < n; c++) sum -= A[row * n + c] * rhs[c];
		rhs[row] = sum / A[row * n + row];
	}
	return 0;
}

/* What the layout this library was built for is called (lib.py checks it) */
EXPORT unsigned int vexsim_layout(void) { return VEXSIM_LAYOUT; }

/* Robot._step_python: one step of the robot in the block b, up to the walls.
 * 0, or 1 when the step's system can't be solved (numpy raises LinAlgError there). */
EXPORT int vexsim_step(double *b, const vexsim_arrays *a, double dt) {
	const int n = (int)b[R_DOF], W = (int)b[R_WHEELS], rows = CHANNELS * W;
	const int drive_motors = (int)b[R_DRIVE_MOTORS], mechanisms = (int)b[R_MECHANISMS];
	double *motors = b + (int)b[R_MOTORS_AT];
	double *mechanism = b + (int)b[R_MECHANISMS_AT];
	double *wheel = b + (int)b[R_WHEELS_AT];
	double *normal = wheel + W_NORMAL * W;
	const double *coupled = wheel + W_COUPLED * W;
	double *qdot = a->qdot, *cg = a->cg;
	const double *C = a->contact_matrix, *M = a->mass_matrix;
	const double *coeff = a->channel_coeff, *scale = a->channel_scale;

	double forces[VEXSIM_MAX_DOF], contact_forces[VEXSIM_MAX_DOF];
	double contact_vel[MAX_ROWS], limit[MAX_ROWS], friction[MAX_ROWS], damping[MAX_ROWS];
	double cross[VEXSIM_MAX_WHEELS];        /* a traction wheel's slip-free damping */
	double damped[VEXSIM_MAX_DOF][MAX_ROWS]; /* C.T @ D */
	double A[VEXSIM_MAX_DOF * VEXSIM_MAX_DOF];
	double u, v, w, mid, c, s;
	int i, j, k;

	/* the wheels' loads, from the last step's ground force */
	normal_loads(W, wheel, b, b[R_GROUND_FX], b[R_GROUND_FY], normal);
	if (b[R_LIFTED] != 0.0) {
		for (i = 0; i < W; i++) normal[i] = 0.0; /* nothing presses the wheels on the floor */
	}

	/* the motors' torques on their groups, then the mechanisms */
	for (i = 0; i < n; i++) forces[i] = 0.0;
	for (i = 0; i < drive_motors; i++) {
		double *m = motors + i * M_SIZE;
		int dof = (int)m[M_DOF];
		forces[dof] += m[M_SIGN] * motor_update(m, b, m[M_SIGN] * qdot[dof], dt);
	}
	for (i = 0; i < mechanisms; i++) mechanism_advance(mechanism + i * K_SIZE, motors, b, dt);

	/* the wheels' contact: smoothed Coulomb friction of contact_vel = C @ qdot */
	for (k = 0; k < rows; k++) {
		double sum = 0.0, t;
		for (j = 0; j < n; j++) sum += C[k * n + j] * qdot[j];
		contact_vel[k] = sum;
		limit[k] = coeff[k] * normal[k / CHANNELS];
		t = tanh(contact_vel[k] / scale[k]); /* smoothed_coulomb */
		friction[k] = limit[k] * t;
		damping[k] = limit[k] * (1.0 - t * t) / scale[k];
	}
	for (i = 0; i < W; i++) { /* Robot._friction_circles */
		cross[i] = 0.0;
		if (coupled[i] != 0.0) {
			k = CHANNELS * i;
			friction_circle(
				contact_vel[k], contact_vel[k + 1], limit[k], scale[k], &friction[k], &friction[k + 1],
				&damping[k], &damping[k + 1], &cross[i]
			);
		}
	}
	/* jacobian = -C.T @ D @ C, with D the damping: diagonal, but for the traction wheels' blocks */
	for (i = 0; i < n; i++) {
		for (k = 0; k < rows; k++) damped[i][k] = C[k * n + i] * damping[k];
		for (j = 0; j < W; j++) {
			if (cross[j] != 0.0) {
				k = CHANNELS * j;
				damped[i][k] += C[(k + 1) * n + i] * cross[j];
				damped[i][k + 1] += C[k * n + i] * cross[j];
			}
		}
	}
	for (i = 0; i < n; i++) {
		double sum = 0.0;
		for (k = 0; k < rows; k++) sum += C[k * n + i] * friction[k];
		contact_forces[i] = -sum; /* -C.T @ friction */
		forces[i] += contact_forces[i];
	}

	u = qdot[0], v = qdot[1], w = qdot[2];
	forces[0] += b[R_MASS] * w * v; /* rotating-frame terms */
	forces[1] -= b[R_MASS] * w * u;
	if (a->external_force[0] != 0.0 || a->external_force[1] != 0.0 || b[R_EXTERNAL_TORQUE] != 0.0) {
		/* the push, turned into the body frame */
		double ec = cos(-b[R_HEADING]), es = sin(-b[R_HEADING]);
		double x = a->external_force[0], y = a->external_force[1];
		forces[0] += ec * x - es * y;
		forces[1] += es * x + ec * y;
		forces[2] += b[R_EXTERNAL_TORQUE];
	}

	/* the linearly implicit Euler update: (M - dt * J) dq = dt * Q */
	for (i = 0; i < n; i++) {
		for (j = 0; j < n; j++) {
			double jacobian = 0.0;
			for (k = 0; k < rows; k++) jacobian -= damped[i][k] * C[k * n + j];
			A[i * n + j] = M[i * n + j] - dt * jacobian;
		}
		forces[i] = dt * forces[i];
	}
	if (solve(n, A, forces)) return 1;
	for (i = 0; i < n; i++) qdot[i] += forces[i];

	u = qdot[0], v = qdot[1], w = qdot[2];
	mid = b[R_HEADING] + 0.5 * w * dt;
	c = cos(mid), s = sin(mid);
	cg[0] += (c * u - s * v) * dt;
	cg[1] += (s * u + c * v) * dt;
	b[R_HEADING] += w * dt;

	if (b[R_EXTERNAL_SUPPLY] == 0.0) { /* PowerSystem.end_step, with Battery.step */
		double load_w = py_max(b[R_LOAD_W], 0.0);
		double current = load_w / py_max(b[R_BUS_VOLTAGE], 1e-3) + b[R_QUIESCENT_A];
		double drawn_mah = py_max(current, 0.0) * dt / 3.6;
		const double *soc_at = b + R_OCV_SOC, *volts_at = b + R_OCV_V;
		int points = (int)b[R_OCV_POINTS];
		double soc, open_circuit;

		b[R_CHARGE_USED_MAH] += drawn_mah;
		b[R_SOC] = py_max(0.0, b[R_SOC] - drawn_mah / b[R_CAPACITY_MAH]);
		b[R_BATTERY_CURRENT_A] = current;
		/* Battery.open_circuit_voltage: numpy.interp over the curve's points */
		soc = b[R_SOC];
		if (soc <= soc_at[0]) {
			open_circuit = volts_at[0];
		} else if (soc >= soc_at[points - 1]) {
			open_circuit = volts_at[points - 1];
		} else {
			double slope;
			for (i = 0; soc >= soc_at[i + 1]; i++) {
			}
			slope = (volts_at[i + 1] - volts_at[i]) / (soc_at[i + 1] - soc_at[i]);
			open_circuit = slope * (soc - soc_at[i]) + volts_at[i];
		}
		/* Battery.terminal_voltage */
		b[R_BUS_VOLTAGE] = py_max(0.0, open_circuit - current * b[R_INTERNAL_RESISTANCE_OHM]);
		b[R_LOAD_W] = 0.0;
	}

	b[R_GROUND_FX] = contact_forces[0], b[R_GROUND_FY] = contact_forces[1];
	for (i = 0; i < W; i++) { /* the wheels' contact state, for whoever looks */
		wheel[W_SLIP * W + i] = contact_vel[CHANNELS * i];
		wheel[W_LATERAL_VELOCITY * W + i] = contact_vel[CHANNELS * i + 1];
		wheel[W_TRACTION_FORCE * W + i] = friction[CHANNELS * i];
		wheel[W_LATERAL_FORCE * W + i] = -friction[CHANNELS * i + 1];
	}
	return 0;
}
