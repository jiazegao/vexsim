"""A config and a route, checked, as the protocol has them (for their editors' endpoints)."""

from __future__ import annotations

import functools
from pathlib import Path

from vexsim.app import configs
from vexsim.app.frames import preview_of
from vexsim.app.workspace import Workspace
from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.ui.protocol import (
    ConfigCheck,
    MotionHintInfo,
    NotRouteFunctionInfo,
    PlacedIssue,
    Preview,
    RouteCheck,
    RouteData,
    RouteDriveInfo,
    RouteFunctionInfo,
    RouteParamInfo,
    RouteStepData,
    TextSpan,
)


def _checked(checked: configs.CheckedConfig) -> ConfigCheck:
    """A checked config as the protocol has it."""

    def span(place: configs.Span | None) -> TextSpan | None:
        if place is None:
            return None
        return TextSpan(
            line=place.line,
            column=place.column,
            end_line=place.end_line,
            end_column=place.end_column,
        )

    config = checked.config
    return ConfigCheck(
        issues=[
            PlacedIssue(
                severity=issue.severity,
                location=issue.location,
                message=issue.message,
                span=span(issue.span),
            )
            for issue in checked.issues
        ],
        robot=config if isinstance(config, RobotConfig) else None,
        field=config if isinstance(config, FieldConfig) else None,
        summary=checked.summary,
        places={item: span(place) for item, place in checked.places.items()},
    )


def _span(place: configs.Span | None) -> TextSpan | None:
    if place is None:
        return None
    return TextSpan(
        line=place.line, column=place.column, end_line=place.end_line, end_column=place.end_column
    )


def _function_info(f, enums) -> RouteFunctionInfo:
    """One of the team's functions (``bridge.functions.Function``) as the editor takes it."""

    def param(p) -> RouteParamInfo:
        values = list(enums[p.enum].values) if p.enum and p.enum in enums else []
        return RouteParamInfo(
            name=p.name, type=p.type, kind=p.kind, default=p.default,
            value=p.literal(tuple(values)), values=values,
        )  # fmt: skip

    hint = None if f.hint is None else MotionHintInfo(motion=f.hint.motion, args=list(f.hint.args))
    return RouteFunctionInfo(
        name=f.name, header=f.header, line=f.line, declaration=f.declaration(),
        params=[param(p) for p in f.params], required=f.required, hint=hint,
        hint_problem=f.hint_problem,
    )  # fmt: skip


def _headers_functions(project: Path, listed: tuple[str, ...]):
    """The functions of ``project``'s own headers that a route doesn't list
    (``bridge.functions.Functions``), read again only when one of those headers changes."""
    from vexsim.app.routes import project_headers

    def stamp(header: str) -> tuple[int, int]:
        try:
            st = (project / header).stat()
        except OSError:  # gone since: find_functions says it's missing
            return (0, -1)
        return (st.st_mtime_ns, st.st_size)

    headers = tuple(h for h in project_headers(project) if h not in listed)
    return _read_functions(str(project), headers, tuple(stamp(h) for h in headers))


@functools.lru_cache(maxsize=16)
def _read_functions(project: str, headers: tuple[str, ...], stamps: tuple[tuple[int, int], ...]):
    from vexsim.bridge.functions import find_functions

    return find_functions(Path(project), list(headers))


def _route_checked(ws: Workspace, file: Path, text: str) -> RouteCheck:
    """A route's text, checked, as the editor takes it (``RouteCheck``)."""
    from vexsim.app import routes
    from vexsim.runtime.follow import drive_geometry

    checked, located = routes.check_text(text, file)
    route = checked.route
    issues = [
        PlacedIssue(severity=i.severity, location=i.location, message=i.message, span=_span(i.span))
        for i in located
    ]
    data = None
    places: dict[str, TextSpan] = {}
    if route is not None:
        data = RouteData(
            name=route.name, start=route.start, robot=route.robot, field=route.field,
            functions=list(route.functions), drive=route.drive,
            steps=[
                RouteStepData(
                    kind=step.kind, target=list(step.target), timeout=step.timeout,
                    side=step.side, options=dict(step.options), function=step.function,
                    args=dict(step.args), label=routes.label(step),
                )  # fmt: skip
                for step in route.steps
            ],
        )  # fmt: skip
        try:
            root, _ = configs._compose(text)
        except Exception:  # it read a moment ago
            root = None
        for where in ["start", *(f"steps[{k}]" for k in range(len(route.steps)))]:
            place = _span(configs.locate(root, where, text, exact=True))
            if place is not None:
                places[where] = place
    found = checked.functions
    functions = [
        _function_info(f, found.enums) for f in (found.functions if found is not None else [])
    ]
    project = routes.project_of(file)
    more = []  # the functions of the project's other headers, for "Add a step" to find
    if found is not None and project is not None and route is not None:
        named = {f.name for f in functions}
        elsewhere = _headers_functions(project, tuple(route.functions))
        more = [
            _function_info(f, elsewhere.enums) for f in elsewhere.functions if f.name not in named
        ]
    others = [
        NotRouteFunctionInfo(name=o.name, header=o.header, line=o.line, why=o.why)
        for o in (found.others if found is not None else [])
    ]
    preview = track = None
    if checked.robot is not None:
        preview = Preview.model_validate(preview_of(checked.robot, checked.field or FieldConfig()))
        track = drive_geometry(checked.robot)[0]

    def listed(path: Path | None) -> str | None:
        try:
            return None if path is None else ws.relative(path)
        except ValueError:
            return None

    named = {
        key: (file.parent / getattr(route, key))
        if route is not None and getattr(route, key)
        else None
        for key in ("robot", "field")
    }
    drive = None
    model = checked.drive
    robot = checked.robot
    if model is None and route is not None and robot is not None:  # what an arc would drive with
        if robot.drivetrain.type in ("differential", "hdrive"):
            model = routes.route_drive(route, robot)
    if model is not None:
        drive = RouteDriveInfo(**{k: getattr(model, k) for k in RouteDriveInfo.model_fields})
    return RouteCheck(
        issues=issues, route=data, functions=functions, more_functions=more, others=others,
        headers=routes.project_headers(project) if project is not None else [],
        preview=preview, track=track, drive=drive, places=places, project=listed(project),
        robot_path=listed(named["robot"]), field_path=listed(named["field"]),
    )  # fmt: skip
