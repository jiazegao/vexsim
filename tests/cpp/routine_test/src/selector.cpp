#include "main.h"
#include "custom/auton.hpp"

// As a team's autonomous selector does: a table of routines, and the one picked runs
using Routine = void (*)();
static const Routine table[] = {alpha, beta, extra::gamma};
int selected = 0;

void run_selected() { table[selected](); }
