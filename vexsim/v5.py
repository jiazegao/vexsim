"""V5 hardware constants shared across the simulator."""

SMART_PORT_COUNT = 21

MOTOR_MAX_MV = 12000
MOTOR_11W_POWER_W = 11.0

# Output free speed of the V5 11W motor for each gear cartridge.
CARTRIDGE_FREE_RPM = {"red": 100.0, "green": 200.0, "blue": 600.0}

# Competition limits. These come from the V5RC game manual and can change by
# season, so the config checker only warns about them.
STARTING_SIZE_LIMIT_IN = 18.0
MOTOR_POWER_BUDGET_W = 88.0
