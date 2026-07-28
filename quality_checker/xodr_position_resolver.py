import math
import xml.etree.ElementTree as ET


class OpenDrivePositionResolver:
    """Resolve OpenSCENARIO LanePosition values to world XY using OpenDRIVE."""

    def __init__(self):
        self._xodr_cache = {}

    def resolve_lane_position_to_world(self, xodr_path, lane_position):
        """
        Resolve a lane position to world coordinates.
        Args:
            xodr_path (_type_): path to the OpenDRIVE file
            lane_position (_type_): plane position object with road_id, lane_id, s, and offset

        Returns:
            _type_: world coordinates (x, y) tuple or None if resolution fails
        """
        if xodr_path is None:
            return None

        xodr_data = self._load_xodr_data(xodr_path)
        if xodr_data is None:
            return None

        try:
            road_id = str(lane_position.road_id)
            lane_id = int(lane_position.lane_id)
            s = float(lane_position.s)
            offset = float(lane_position.offset)
        except Exception:
            return None

        road_data = xodr_data.get(road_id)
        if road_data is None:
            return None

        x_ref, y_ref, hdg = self._eval_road_reference_line(road_data, s)
        if x_ref is None:
            return None

        lane_center_offset = self._eval_lane_center_offset(road_data, lane_id, s)
        if lane_center_offset is None:
            return None

        t = lane_center_offset + offset
        x_world = x_ref - t * math.sin(hdg)
        y_world = y_ref + t * math.cos(hdg)
        return (x_world, y_world)

    def _load_xodr_data(self, xodr_path):
        """
        load and parse OpenDRIVE data from the given path, with caching to avoid redundant parsing.
        Args:
            xodr_path (_type_): path to the OpenDRIVE file

        Returns:
            _type_: parsed OpenDRIVE data or None if parsing fails
        """
        cache_key = str(xodr_path)
        if cache_key in self._xodr_cache:
            return self._xodr_cache[cache_key]

        try:
            tree = ET.parse(xodr_path)
            root = tree.getroot()
        except Exception:
            self._xodr_cache[cache_key] = None
            return None

        roads = {}
        for road in root.iter():
            if not road.tag.endswith("road"):
                continue

            road_id = str(road.attrib.get("id", ""))
            try:
                road_length = float(road.attrib.get("length", 0.0))
            except Exception:
                road_length = 0.0

            plan_view = None
            lanes = None
            for child in road:
                if child.tag.endswith("planView"):
                    plan_view = child
                elif child.tag.endswith("lanes"):
                    lanes = child

            geometries = []
            if plan_view is not None:
                for geom in plan_view:
                    if not geom.tag.endswith("geometry"):
                        continue
                    try:
                        geom_s = float(geom.attrib.get("s", 0.0))
                        geom_x = float(geom.attrib.get("x", 0.0))
                        geom_y = float(geom.attrib.get("y", 0.0))
                        geom_hdg = float(geom.attrib.get("hdg", 0.0))
                        geom_len = float(geom.attrib.get("length", 0.0))
                    except Exception:
                        continue

                    geom_type = "line"
                    curvature = 0.0
                    for gc in geom:
                        if gc.tag.endswith("arc"):
                            geom_type = "arc"
                            try:
                                curvature = float(gc.attrib.get("curvature", 0.0))
                            except Exception:
                                curvature = 0.0
                            break
                        if gc.tag.endswith("line"):
                            geom_type = "line"
                            break

                    geometries.append(
                        {
                            "s": geom_s,
                            "x": geom_x,
                            "y": geom_y,
                            "hdg": geom_hdg,
                            "length": geom_len,
                            "type": geom_type,
                            "curvature": curvature,
                        }
                    )
            geometries.sort(key=lambda g: g["s"])

            lane_offsets = []
            lane_sections = []
            if lanes is not None:
                for ln_child in lanes:
                    if ln_child.tag.endswith("laneOffset"):
                        lane_offsets.append(
                            {
                                "s": float(ln_child.attrib.get("s", 0.0)),
                                "a": float(ln_child.attrib.get("a", 0.0)),
                                "b": float(ln_child.attrib.get("b", 0.0)),
                                "c": float(ln_child.attrib.get("c", 0.0)),
                                "d": float(ln_child.attrib.get("d", 0.0)),
                            }
                        )
                    elif ln_child.tag.endswith("laneSection"):
                        section = {
                            "s": float(ln_child.attrib.get("s", 0.0)),
                            "lanes": {},
                        }

                        for side in ln_child:
                            if not (
                                side.tag.endswith("left")
                                or side.tag.endswith("right")
                                or side.tag.endswith("center")
                            ):
                                continue
                            for lane in side:
                                if not lane.tag.endswith("lane"):
                                    continue
                                try:
                                    lane_id = int(lane.attrib.get("id", 0))
                                except Exception:
                                    continue
                                widths = []
                                for lane_child in lane:
                                    if lane_child.tag.endswith("width"):
                                        widths.append(
                                            {
                                                "sOffset": float(
                                                    lane_child.attrib.get(
                                                        "sOffset", 0.0
                                                    )
                                                ),
                                                "a": float(
                                                    lane_child.attrib.get("a", 0.0)
                                                ),
                                                "b": float(
                                                    lane_child.attrib.get("b", 0.0)
                                                ),
                                                "c": float(
                                                    lane_child.attrib.get("c", 0.0)
                                                ),
                                                "d": float(
                                                    lane_child.attrib.get("d", 0.0)
                                                ),
                                            }
                                        )
                                widths.sort(key=lambda w: w["sOffset"])
                                section["lanes"][lane_id] = widths

                        lane_sections.append(section)

            lane_offsets.sort(key=lambda lo: lo["s"])
            lane_sections.sort(key=lambda ls: ls["s"])

            roads[road_id] = {
                "length": road_length,
                "geometries": geometries,
                "lane_offsets": lane_offsets,
                "lane_sections": lane_sections,
            }

        self._xodr_cache[cache_key] = roads
        return roads

    @staticmethod
    def _eval_poly(coeffs, ds):
        """
        evaluate a cubic polynomial with given coefficients at a distance ds.
        Args:
            coeffs (_type_): dictionary with keys 'a', 'b', 'c', 'd' representing polynomial coefficients
            ds (_type_): distance along the polynomial to evaluate

        Returns:
            _type_: evaluated polynomial value at distance ds
        """
        return (
            coeffs["a"]
            + coeffs["b"] * ds
            + coeffs["c"] * ds * ds
            + coeffs["d"] * ds * ds * ds
        )

    def _eval_road_reference_line(self, road_data, s):
        """
        evaluate reference line position and heading for a given road data and distance s along the road.
        Args:
            road_data (_type_): dictionary containing road geometries and lane information
            s (_type_): distance along the road to evaluate

        Returns:
            _type_: tuple of (x, y, heading) at the specified distance
        """
        geoms = road_data.get("geometries", [])
        if len(geoms) == 0:
            return (None, None, None)

        road_length = max(float(road_data.get("length", 0.0)), 0.0)
        s_clamped = min(
            max(float(s), 0.0), road_length if road_length > 0 else float(s)
        )

        geom = geoms[0]
        for candidate in geoms:
            if candidate["s"] <= s_clamped:
                geom = candidate
            else:
                break

        ds = max(0.0, s_clamped - geom["s"])
        ds = min(ds, max(geom["length"], 0.0))

        x0 = geom["x"]
        y0 = geom["y"]
        hdg0 = geom["hdg"]
        if geom["type"] == "arc" and abs(geom["curvature"]) >= 1e-12:
            k = geom["curvature"]
            x = x0 + (math.sin(hdg0 + k * ds) - math.sin(hdg0)) / k
            y = y0 - (math.cos(hdg0 + k * ds) - math.cos(hdg0)) / k
            hdg = hdg0 + k * ds
        else:
            x = x0 + ds * math.cos(hdg0)
            y = y0 + ds * math.sin(hdg0)
            hdg = hdg0

        return (x, y, hdg)

    def _eval_lane_center_offset(self, road_data, lane_id, s):
        """
        evaluate the lateral offset of the lane center from the reference line for a given lane_id and distance s along the road.
        Args:
            road_data (_type_): dictionary containing road geometries and lane information
            lane_id (_type_): ID of the lane for which to evaluate the offset
            s (_type_): distance along the road to evaluate

        Returns:
            _type_: offset
        """
        lane_offsets = road_data.get("lane_offsets", [])
        lane_sections = road_data.get("lane_sections", [])

        base_offset = 0.0
        if len(lane_offsets) > 0:
            lane_offset = lane_offsets[0]
            for candidate in lane_offsets:
                if candidate["s"] <= s:
                    lane_offset = candidate
                else:
                    break
            base_offset = self._eval_poly(lane_offset, s - lane_offset["s"])

        if lane_id == 0:
            return base_offset

        if len(lane_sections) == 0:
            return None

        lane_section = lane_sections[0]
        for candidate in lane_sections:
            if candidate["s"] <= s:
                lane_section = candidate
            else:
                break

        ds_section = s - lane_section["s"]

        def eval_lane_width(target_lane_id):
            widths = lane_section["lanes"].get(target_lane_id)
            if not widths:
                return None
            width = widths[0]
            for candidate in widths:
                if candidate["sOffset"] <= ds_section:
                    width = candidate
                else:
                    break
            return self._eval_poly(width, ds_section - width["sOffset"])

        t = base_offset
        if lane_id > 0:
            for lid in range(1, lane_id + 1):
                w = eval_lane_width(lid)
                if w is None:
                    return None
                if lid < lane_id:
                    t += w
                else:
                    t += 0.5 * w
        else:
            for lid in range(-1, lane_id - 1, -1):
                w = eval_lane_width(lid)
                if w is None:
                    return None
                if lid > lane_id:
                    t -= w
                else:
                    t -= 0.5 * w

        return t
