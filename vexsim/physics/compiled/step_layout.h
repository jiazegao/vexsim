/* Where each number of a robot lives in its block of doubles, for step.c.
 * Written by `python -m vexsim.physics.compiled` from the tables in layout.py:
 * change those, not this. */
#ifndef VEXSIM_STEP_LAYOUT_H
#define VEXSIM_STEP_LAYOUT_H

#define VEXSIM_LAYOUT 0x1d70ca61u
#define VEXSIM_MAX_DOF 16
#define VEXSIM_MAX_WHEELS 32
#define VEXSIM_MAX_OCV 32

/* the robot's record, at the block's start */
enum {
	R_DOF = 0,
	R_WHEELS = 1,
	R_DRIVE_MOTORS = 2,
	R_MOTORS = 3,
	R_MECHANISMS = 4,
	R_MOTORS_AT = 5,
	R_MECHANISMS_AT = 6,
	R_WHEELS_AT = 7,
	R_MASS = 8,
	R_HEADING = 9,
	R_LIFTED = 10,
	R_EXTERNAL_TORQUE = 11,
	R_GROUND_FX = 12,
	R_GROUND_FY = 13,
	R_STIFFNESS = 14,
	R_WEIGHT = 15,
	R_CG_HEIGHT = 16,
	R_EXTERNAL_SUPPLY = 17,
	R_BUS_VOLTAGE = 18,
	R_LOAD_W = 19,
	R_BATTERY_CURRENT_A = 20,
	R_QUIESCENT_A = 21,
	R_SOC = 22,
	R_CHARGE_USED_MAH = 23,
	R_CAPACITY_MAH = 24,
	R_INTERNAL_RESISTANCE_OHM = 25,
	R_OCV_POINTS = 26,
	R_OCV_SOC = 27,
	R_OCV_V = 59,
	R_SIZE = 91,
};

/* a motor's record */
enum {
	M_POSITION = 0,
	M_VELOCITY = 1,
	M_CURRENT = 2,
	M_VOLTAGE = 3,
	M_TORQUE = 4,
	M_POWER_IN = 5,
	M_CURRENT_LIMITED = 6,
	M_MODE = 7,
	M_BRAKE_MODE = 8,
	M_VOLTAGE_CMD = 9,
	M_VELOCITY_CMD = 10,
	M_POSITION_CMD = 11,
	M_MAX_SPEED = 12,
	M_HOLD_TARGET = 13,
	M_INTEGRAL_V = 14,
	M_VELOCITY_EST = 15,
	M_ACCEL_EST = 16,
	M_CURRENT_LIMIT = 17,
	M_SUPPLY_CURRENT_CAP = 18,
	M_WINDING_C = 19,
	M_HOUSING_C = 20,
	M_SIGN = 21,
	M_DOF = 22,
	M_RATIO = 23,
	M_RATED_SPEED = 24,
	M_RESISTANCE_OHM = 25,
	M_KT = 26,
	M_KE = 27,
	M_COULOMB_NM = 28,
	M_VISCOUS_NM_S = 29,
	M_SMOOTHING_RAD_S = 30,
	M_VELOCITY_KP = 31,
	M_VELOCITY_KI = 32,
	M_VELOCITY_FILTER_S = 33,
	M_INTEGRAL_GATE = 34,
	M_POSITION_KP = 35,
	M_VOLTAGE_CAP = 36,
	M_AMBIENT_C = 37,
	M_WINDING_HEAT_CAPACITY_J_PER_K = 38,
	M_HOUSING_HEAT_CAPACITY_J_PER_K = 39,
	M_WINDING_TO_HOUSING_K_PER_W = 40,
	M_HOUSING_TO_AMBIENT_K_PER_W = 41,
	M_DERATE_START_C = 42,
	M_DERATE_STEP_C = 43,
	M_SIZE = 44,
};

/* a mechanism's record */
enum {
	K_ANGLE = 0,
	K_SPEED = 1,
	K_INERTIA = 2,
	K_LOAD = 3,
	K_FRICTION = 4,
	K_LOW = 5,
	K_HIGH = 6,
	K_FIRST_MOTOR = 7,
	K_MOTOR_COUNT = 8,
	K_SIZE = 9,
};

/* the wheels' columns: column c of wheel i is at wheels_at + c * wheels + i */
enum {
	W_BASE = 0,
	W_SENS_X = 1,
	W_SENS_Y = 2,
	W_POS_X = 3,
	W_POS_Y = 4,
	W_DROP = 5,
	W_COUPLED = 6,
	W_NORMAL = 7,
	W_SLIP = 8,
	W_LATERAL_VELOCITY = 9,
	W_TRACTION_FORCE = 10,
	W_LATERAL_FORCE = 11,
	W_COLUMNS = 12,
};

/* V5Motor's control and brake modes */
enum { MODE_STOPPED, MODE_VOLTAGE, MODE_VELOCITY, MODE_POSITION };
enum { BRAKE_COAST, BRAKE_BRAKE, BRAKE_HOLD };

/* the robot's NumPy arrays */
typedef struct {
	double *qdot;
	double *cg;
	double *external_force;
	double *contact_matrix;
	double *mass_matrix;
	double *channel_coeff;
	double *channel_scale;
} vexsim_arrays;

#endif
