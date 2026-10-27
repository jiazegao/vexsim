#pragma once
// The routines, declared as team 1239E declares theirs: vexsim lists the functions here
// that take no arguments, and runs the one picked in place of the one autonomous() calls.

void alpha();  // the selector's first
void beta();   // calls alpha() itself
namespace extra {
void gamma() noexcept;
}
void delta();  // defined beside autonomous(), which calls it directly: no switching that

void ghost();            // declared, never defined
void drive_for(int ms);  // takes an argument: not a routine
int score();             // returns a value: not a routine
