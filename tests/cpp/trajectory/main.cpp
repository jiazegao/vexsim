// Prints the plans vexsim/trajectory.hpp makes, for tests/test_motions.py to compare with the
// Python ones (vexsim/algorithms/control/trajectory.py). Reads lines from stdin:
//   arc X Y HEADING RADIUS TURN FORWARDS SPEED MAXV MAXA MAXLAT TRACK
//   path X Y HEADING FORWARDS END SPEED MAXV MAXA MAXLAT TRACK PX PY [PX PY]...   (END: nan for none)
// and prints, for each, "plan N" and N lines of t s x y heading v omega a alpha.
#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <string>
#include <vector>

#include "vexsim/trajectory.hpp"

int main() {
	std::string line;
	char buffer[8192];
	while (std::fgets(buffer, sizeof buffer, stdin)) {
		std::istringstream in(buffer);
		std::string kind;
		in >> kind;
		vexsim::Trajectory plan;
		if (kind == "arc") {
			double x, y, h, r, turn, speed;
			int forwards;
			vexsim::Limits l;
			in >> x >> y >> h >> r >> turn >> forwards >> speed >> l.maxVelocity >> l.maxAccel >> l.maxLateralAccel >>
			    l.trackWidth;
			plan = vexsim::planArc(x, y, h, r, turn, forwards != 0, speed, l);
		} else if (kind == "path") {
			double x, y, h, speed;
			std::string end;
			int forwards;
			vexsim::Limits l;
			in >> x >> y >> h >> forwards >> end >> speed >> l.maxVelocity >> l.maxAccel >> l.maxLateralAccel >>
			    l.trackWidth;
			std::vector<vexsim::Waypoint> points;
			double px, py;
			while (in >> px >> py) points.push_back({px, py});
			double endHeading = end == "nan" ? std::nan("") : std::strtod(end.c_str(), nullptr);
			plan = vexsim::planPath(x, y, h, points, forwards != 0, endHeading, speed, l);
		} else {
			continue;
		}
		std::printf("plan %zu\n", plan.size());
		for (const vexsim::State& s : plan)
			std::printf("%.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g\n", s.t, s.s, s.x, s.y, s.heading,
			            s.v, s.omega, s.a, s.alpha);
	}
	return 0;
}
