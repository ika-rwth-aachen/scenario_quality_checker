
from collections import Counter
import collections
import csv
import io
from datetime import datetime
from loguru import logger
import numpy as np
import os
import collections
import pandas as pd
from pathlib import Path
import tempfile
import subprocess
import shlex
import shutil
from scenariogeneration import xosc
import scipy as sp
import shapely
import typer

from xml.sax.handler import ContentHandler
from xml.sax import make_parser
import xml.etree.ElementTree as ET
import xmlschema

from .config import Config
from .pdf import *
from .pdf_report_creator import *
from .xodr_position_resolver import OpenDrivePositionResolver

# Default schema path relative to the package location
DEFAULT_SCHEMA_PATH = Path(__file__).parent.parent / "schemas"

app = typer.Typer()


class FileQualityChecker:
    def __init__(self, scenario_path, schema_path, esmini_path=None, print_log=False):
        """
        Initialize the checker and run the full validation pipeline.
        Args:
            scenario_path: Path to the .xosc scenario file.
            schema_path: Path to the directory with XSD schemas.
            use_simulation: Whether to use simulation for dynamic checks.
            print_log: Whether to emit log output.
        """
        self.file_path = scenario_path
        self.print_log = print_log
        self.esmini_path = esmini_path

        self.xml_loadable = False
        self.xsd_valid = False
        self.xsd_errors = []
        self.version = None
        self.author = None
        self.date = None
        self.scenario = None
        self.road_user_counts = Counter()
        self.file_errors = ([], [], [], [])
        self.position_resolution_warnings = []
        self.dynamic_errors = None
        self.dynamic_data = None
        self.simulation_status = 'not done'
        self._xodr_resolver = OpenDrivePositionResolver()

        if self.print_log:
            logger.info(f'Starting analysis of {self.file_path}')

        # Parse XML early to avoid downstream schema/scenario errors.
        self.xml_loadable = self.is_xml_loadable()
        if not self.xml_loadable:
            return
        elif self.print_log == True:
            logger.info('XML is loadable')

        # Validate against the matching OpenSCENARIO XSD.
        self.xsd_valid, self.version = self.is_xsd_valid(schema_path)
        if not self.xsd_valid:
            return
        elif print_log == True:
            logger.info('XSD is valid')

        # Parse with scenariogeneration to access scenario structure.
        self.scenario = self.load_openscenario()

        if self.scenario is None:
            return

        # Metadata is read from the parsed scenario header.
        self.author = self.scenario.header.get_attributes()['author']
        self.date = self.get_date()

        # File-level checks (entities, init positions, intersections, add/remove).
        entities, self.file_errors = self.check_file_errors()
        self.road_user_counts = Counter(entities.values())
        self.road_user_counts['total'] = str(len(entities))

        # Dynamic checks (acceleration and swim angle thresholds).
        self.dynamic_errors = self.check_dynamic_errors()

    def to_summary_row(self):
        """
        Return a compact summary tuple for aggregated reports.
        Args:
            None
        return: Tuple of (file_path, xml_loadable, xsd_valid, simulation_status, n_file_errors, n_dynamic_errors)
        """
        # Keep values stable even when earlier stages failed.
        if not self.xml_loadable:
            return (self.file_path, False, False, self.simulation_status, '-', '-')

        if not self.xsd_valid:
            return (self.file_path, True, False, self.simulation_status, '-', '-')

        if self.scenario is None:
            return (self.file_path, True, True, self.simulation_status, '-', '-')

        try:
            file_error_count = sum(len(items) for items in self.file_errors)
        except Exception:
            file_error_count = '-'

        try:
            # Default to empty lists when dynamic errors are missing.
            dynamic_error_groups = self.dynamic_errors or ([], [], [], [])
            dynamic_error_count = sum(len(items) for items in dynamic_error_groups)
        except Exception:
            dynamic_error_count = '-'

        return (self.file_path, True, True, self.simulation_status, file_error_count, dynamic_error_count)

    def is_xml_loadable(self):
        """
        Check whether the file can be parsed as XML.
        Args:
            None
        return: True if the file parses as XML, otherwise False.
        """
        parser = make_parser()
        parser.setContentHandler(ContentHandler())
        try:
            parser.parse(self.file_path)
            return True
        except Exception as e:
            return False

    def is_xsd_valid(self, schema_path):
        """
        Check whether the file validates against an available XSD schema.
        Args:
            schema_path: Path to the directory with XSD schemas.
        return: (is_valid, xsd_version)
        """
        tree = ET.parse(self.file_path)
        root = tree.getroot()

        revMajor = root[0].attrib['revMajor']
        revMinor = root[0].attrib['revMinor']
        xsd_version = revMajor + '-' + revMinor

        # Reset stored errors on each validation run.
        self.xsd_errors = []

        # Schema files exist for v1.x only; v2+ is treated as unsupported here.
        if int(revMajor) < 2:
            file = Path('OpenSCENARIO_' + xsd_version + '.xsd')
            schema_file = schema_path / file
        else:
            msg = f"File version {xsd_version} is not supported (no schema for revMajor >= 2)."
            self.xsd_errors.append(msg)
            if self.print_log:
                logger.error(msg)
            return (False, xsd_version)

        if not os.path.isfile(schema_file):
            msg = f"Schema file for version {xsd_version} not available: {schema_file}"
            self.xsd_errors.append(msg)
            if self.print_log:
                logger.error(msg)
            return (False, xsd_version)

        xsd = xmlschema.XMLSchema(schema_file)
        is_valid = xsd.is_valid(self.file_path)

        # If validation fails, collect and log detailed errors.
        if not is_valid:
            try:
                # Limit the number of stored errors to keep PDFs readable.
                max_errors = 20
                for idx, error in enumerate(xsd.iter_errors(self.file_path)):
                    if idx >= max_errors:
                        more_msg = f"... and more XSD errors (showing first {max_errors})."
                        self.xsd_errors.append(more_msg)
                        if self.print_log:
                            logger.error(more_msg)
                        break
                    # Build a concise description including path and message.
                    err_msg = f"{error.path}: {error.message}"
                    self.xsd_errors.append(err_msg)
                    if self.print_log:
                        logger.error(
                            f"XSD validation error in {self.file_path} (version {xsd_version}): {err_msg}"
                        )
            except Exception as e:
                fallback_msg = f"Failed to collect XSD validation errors for {self.file_path}: {e}"
                self.xsd_errors.append(fallback_msg)
                if self.print_log:
                    logger.error(fallback_msg)

        return (is_valid, xsd_version)

    def load_openscenario(self):
        """
        Load an OpenSCENARIO file (.xosc) via scenariogeneration.
        Args:
            None
        return: Parsed scenariogeneration object or None on failure.
        """
        temp_file = self._process_xosc_file()
        try:
            scenario = xosc.ParseOpenScenario(temp_file)
            return scenario
        finally:
            # cleanup temp file
            temp_path = Path(temp_file)
            if temp_path.exists():
                temp_path.unlink()

    def _process_xosc_file(self):
        """
        Create a temp .xosc with parameter placeholders resolved.
        Args:
            None
        return: Path to the temporary .xosc file.
        """
        parameters = self._load_parameter_declarations_outside_storyboard()

        with open(self.file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        updated_content = self._replace_parameters_in_content(content, parameters)

        # Write the processed scenario into the persistent results/tmp folder
        # to avoid OS-level temp paths that might be hard to inspect.
        project_root = Path.cwd()
        tmp_root = project_root / "results" / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)

        temp_path = tmp_root / f"processed_{Path(self.file_path).name}"
        with open(temp_path, mode="w", encoding="utf-8") as temp:
            temp.write(updated_content)
        return temp_path
    
    def get_date(self):
        """
        Extract scenario date from the file header (if present).
        Args:
            None
        return: Date string in DD.MM.YYYY format or None.
        """
        tree = ET.parse(self.file_path)
        root = tree.getroot()
        header = root.find("FileHeader")
        if header is not None and 'date' in header.attrib:
            date = header.attrib['date']
            date = datetime.fromisoformat(date)
            return date.strftime("%d.%m.%Y")
        else:
            return None
    
    def check_file_errors(self):
        """
        Check for entity definition, init, and intersection issues.
        Args:
            None
        return: (entities_dict, file_errors_tuple)
        """
        entities = self._get_entities()
        entity_names = list(entities.keys())
        missing_entity_definitions = self._check_actors_defined(entity_names)

        init_positions, parked_entities, unresolved_no_xodr, unresolved_conversion = self._get_initial_positions(entity_names)

        self.position_resolution_warnings = []
        if len(unresolved_no_xodr) > 0:
            self.position_resolution_warnings.append(
                "Warning: Initial overlap for local LanePosition is not assessable without valid OpenDRIVE (.xodr): "
                + ", ".join(sorted(unresolved_no_xodr))
            )
        if len(unresolved_conversion) > 0:
            self.position_resolution_warnings.append(
                "Warning: Initial overlap could not be resolved from OpenDRIVE for: "
                + ", ".join(sorted(unresolved_conversion))
            )

        identical_initposition_entities = self._get_identical_initposition_entities(init_positions)
        intersecting_entities = self._get_intersecting_entities(init_positions)

        added_entities, removed_entities = self._get_added_and_removed_entities()
        missing_in = self._check_in_out_entities(init_positions, parked_entities, added_entities, removed_entities)
        
        return entities, (missing_entity_definitions, identical_initposition_entities, intersecting_entities, missing_in )
    
    def check_dynamic_errors(self):   
        """
        Check for acceleration and swim angle threshold violations.
        Args:
            None
        return: (acceleration_errors, acceleration_warnings, swimangle_errors, swimangle_warnings)
        """
        acceleration_errors = []
        acceleration_warnings = []
        swimangle_errors = []
        swimangle_warnings = []

        dynamic_data = self._get_dynamic_data()
        if len(dynamic_data) == 0:
            return (acceleration_errors, acceleration_warnings, swimangle_errors, swimangle_warnings)

        for entity_name in dynamic_data.keys():
            positions, times = dynamic_data[entity_name]

            if len(times) == 0 or any(t is None for t in times):
                continue
            
            df = self._build_dynamic_data_df(positions, times)
            df = self._calculate_acceleration_swimangle(df)

            if 'ego' in entity_name:
                if np.any(np.abs(df.acceleration) > Config.ACCELERATION_ERROR_THRESHOLD):
                    acceleration_errors.append(entity_name)
                elif np.any(np.abs(df.acceleration) > Config.ACCELERATION_WARNING_THRESHOLD):
                    acceleration_warnings.append(entity_name)

                if np.any(np.abs(df.swimangle) > Config.SWIMANGLE_ERROR_THRESHOLD):
                    swimangle_errors.append(entity_name)
                elif np.any(np.abs(df.swimangle) > Config.SWIMANGLE_WARNING_THRESHOLD):
                    swimangle_warnings.append(entity_name)
            else:
                if np.any(np.abs(df.acceleration) > Config.ACCELERATION_ERROR_THRESHOLD):
                    acceleration_errors.append(entity_name)
                elif np.any(np.abs(df.acceleration) > Config.ACCELERATION_WARNING_THRESHOLD):
                    acceleration_warnings.append(entity_name)
                if np.any(np.abs(df.swimangle) > Config.SWIMANGLE_ERROR_THRESHOLD):
                    swimangle_errors.append(entity_name)
                elif np.any(np.abs(df.swimangle) > Config.SWIMANGLE_WARNING_THRESHOLD):
                    swimangle_warnings.append(entity_name)
            
        return (
            acceleration_errors, acceleration_warnings, 
            swimangle_errors, swimangle_warnings
            )
    
    def _get_dynamic_data(self):
        """
        Return positions and times for each actor's trajectory events.
        Args:
            use_simulation: Whether to use simulation for dynamic checks.
            esmini_path: Path to the esmini executable.
        return: Dict mapping entity name to (positions, times).
        """
        # Make sure that calculation is only done once.
        if self.dynamic_data is not None:
            return self.dynamic_data

        # If requested, derive trajectories from an external simulator (e.g. esmini).
        if self.esmini_path:
            try:
                self.dynamic_data = self._get_dynamic_data_from_simulation()
                self.simulation_status = 'succeeded'
                return self.dynamic_data
            except Exception as e:
                self.simulation_status = 'failed'
                if self.print_log:
                    logger.warning(
                        f"Simulation-based dynamics extraction failed for {self.file_path}: {e}. "
                        "Falling back to trajectory actions from the scenario file."
                    )
                self.dynamic_data = self._get_dynamic_data_from_scenario()
                return self.dynamic_data

        self.simulation_status = 'not done'
        self.dynamic_data = self._get_dynamic_data_from_scenario()
        return self.dynamic_data

    def _get_dynamic_data_from_scenario(self):
        """Extract dynamic data directly from scenario trajectory/route actions."""
        dynamic_data = {}

        for story in self.scenario.storyboard.stories:
            for act in story.acts:
                for maneuvergroup in act.maneuvergroup:
                    # Per definition only one actor per maneuver group.
                    actor_name = maneuvergroup.actors.actors[0].entity

                    for maneuver in maneuvergroup.maneuvers:
                        for event in maneuver.events:
                            for action in event.action:
                                if 'trajectory' in dir(action.action):
                                    times = action.action.trajectory.shapes.time
                                    positions = action.action.trajectory.shapes.positions
                                    if actor_name in dynamic_data:
                                        old_positions, old_times = dynamic_data[actor_name]
                                        dynamic_data[actor_name] = (old_positions + positions, old_times + times)
                                    else:
                                        dynamic_data[actor_name] = (positions, times)
                                elif 'route' in dir(action.action):
                                    positions = [waypoint.position for waypoint in action.action.route.waypoints]
                                    times = [None] * len(positions)
                                    if actor_name in dynamic_data:
                                        old_positions, old_times = dynamic_data[actor_name]
                                        dynamic_data[actor_name] = (old_positions + positions, old_times + times)
                                    else:
                                        dynamic_data[actor_name] = (positions, times)
                                else:
                                    pass

        return dynamic_data

    def _get_dynamic_data_from_simulation(self):
        """Run esmini and build dynamic_data from its log.

        The esmini command is currently hard-coded. It runs esmini in
        headless mode on the current scenario file and writes a CSV log
        which is then parsed for dynamic checks.
        """
        # Use a persistent temp folder under results/tmp for easier
        # inspection of intermediate files and logs.
        project_root = Path.cwd()
        tmp_root = project_root / "results" / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)

        scenario_tmp = tmp_root / "scenario_for_esmini.xosc"
        shutil.copy2(self.file_path, scenario_tmp)

        # Optionally adjust RoadNetwork -> LogicFile so that any referenced
        # OpenDRIVE file is resolved to an absolute path; otherwise keep
        # RoadNetwork but remove invalid LogicFile children.
        try:
            tree = ET.parse(scenario_tmp)
            root = tree.getroot()
            xosc_dir = Path(self.file_path).parent

            road_network = root.find("RoadNetwork")
            if road_network is not None:
                logic_file = road_network.find("LogicFile")
                if logic_file is not None and "filepath" in logic_file.attrib:
                    rel_path = logic_file.attrib["filepath"]
                    candidate = (xosc_dir / rel_path).resolve()
                    if candidate.is_file():
                        logic_file.set("filepath", str(candidate))
                    else:
                        # No valid .xodr found: keep an empty RoadNetwork.
                        for child in list(road_network):
                            road_network.remove(child)
                else:
                    # No LogicFile defined: keep an empty RoadNetwork.
                    for child in list(road_network):
                        road_network.remove(child)

            # Convert all remaining relative path-like attributes to absolute
            # paths, so the copied scenario in results/tmp can be loaded
            # without relying on its original working directory.
            for elem in root.iter():
                for attr_name, attr_value in list(elem.attrib.items()):
                    if not attr_value:
                        continue

                    val = attr_value.strip()
                    if not ("/" in val or "\\" in val or val.startswith("..")):
                        continue

                    # Skip already-absolute Windows paths (e.g. C:\...).
                    if os.path.isabs(val):
                        continue

                    candidate = (xosc_dir / val).resolve()
                    if candidate.exists():
                        elem.set(attr_name, str(candidate))

            tree.write(scenario_tmp, encoding="utf-8", xml_declaration=True)
        except Exception:
            # If anything goes wrong while tweaking RoadNetwork, fall back
            # to the plain copied scenario file.
            pass

        log_file = tmp_root / "esmini_log.csv"

        cmd = [
            self.esmini_path,
            "--headless",
            "--csv_logger",
            str(log_file),
            "--osc",
            str(scenario_tmp),
        ]

        # Run esmini quietly (no console spam); only use return code
        # for error handling. Detailed issues are still logged via
        # the CSV and our own logger.
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if result.returncode != 0:
            logger.error(
                f"esmini command failed with exit code {result.returncode} "
                f"while running {scenario_tmp}"
            )
            raise RuntimeError(
                f"Simulator command failed with exit code {result.returncode}"
            )

        if not log_file.exists():
            raise RuntimeError(
                f"Simulator finished successfully, but log file {log_file} was not created. "
                "Check the hard-coded esmini command."
            )

        # Parse simulation output and then clean up temporary artifacts
        dynamic_data = self._parse_simulation_log(log_file)

        try:
            if scenario_tmp.exists():
                scenario_tmp.unlink()
            if log_file.exists():
                log_file.unlink()
            # Remove tmp_root only when it is empty; ignore errors if not.
            try:
                tmp_root.rmdir()
            except OSError:
                pass
        except Exception:
            pass

        return dynamic_data

    def get_xodr_path(self):
        """Return the resolved OpenDRIVE (.xodr) file path if available.

        The method inspects the original scenario's RoadNetwork/LogicFile
        element and resolves a relative "filepath" against the scenario
        directory. If the referenced file exists, its absolute Path is
        returned; otherwise, None is returned.
        """
        try:
            tree = ET.parse(self.file_path)
            root = tree.getroot()
        except Exception:
            return None

        road_network = root.find("RoadNetwork")
        if road_network is None:
            return None

        logic_file = road_network.find("LogicFile")
        if logic_file is None:
            return None

        rel_path = logic_file.attrib.get("filepath")
        if not rel_path:
            return None

        scenario_dir = Path(self.file_path).parent
        candidate = (scenario_dir / rel_path).resolve()
        if candidate.is_file():
            return candidate
        return None

    def _parse_simulation_log(self, log_file: Path):
        """Parse a simulator log file into the dynamic_data structure.

        Currently supports the CSV format written by esmini's --csv_logger,
        which looks like:

        - A few metadata lines (git rev, build version, etc.)
        - One long header line starting with "Index [-] , TimeStamp [s] , ..."
        - One data row per timestamp containing columns for #1, #2, ...
          entities (Entitity_Name, World_Position_X/Y, World_Heading_Angle, ...).
        """
        dynamic_data = {}

        # Read all lines first so we can skip esmini's metadata banner and
        # start CSV parsing at the actual header row.
        with open(log_file, encoding="utf-8") as f:
            lines = f.readlines()

        header_index = None
        for idx, line in enumerate(lines):
            if "Index" in line and "TimeStamp" in line:
                header_index = idx
                break

        if header_index is None:
            raise RuntimeError(
                "Simulation log file does not contain an esmini CSV header line "
                "(expected a line starting with 'Index [-] , TimeStamp [s] , ...')."
            )

        csv_text = "".join(lines[header_index:])
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            raise RuntimeError("Simulation log file has no header row.")

        # esmini's CSV headers often contain leading/trailing spaces around
        # names (e.g. " TimeStamp [s] "). We therefore build a mapping
        # from stripped header names to their original forms and use the
        # original names when indexing row dictionaries.
        original_headers = [h for h in reader.fieldnames if h is not None]
        header_map = {h.strip(): h for h in original_headers}
        headers = list(header_map.keys())

        # Identify the global time column (TimeStamp [s]).
        time_col = None
        for name in headers:
            if "timestamp" in name.lower():
                time_col = header_map[name]
                break

        if not time_col:
            raise RuntimeError(
                "Simulation log file is missing a TimeStamp column "
                "(expected something like 'TimeStamp [s]')."
            )

        entity_slots = []
        for name_col_stripped in headers:
            if "entitity_name" in name_col_stripped.lower():  # note: esmini spelling
                prefix = name_col_stripped.split("Entitity_Name")[0].strip()  # e.g. "#1"

                def _find_with_prefix(suffix: str):
                    for h in headers:
                        if h.startswith(prefix) and suffix in h:
                            return h
                    return None

                x_col_stripped = _find_with_prefix("World_Position_X")
                y_col_stripped = _find_with_prefix("World_Position_Y")
                h_col_stripped = _find_with_prefix("World_Heading_Angle")

                if x_col_stripped and y_col_stripped:
                    entity_slots.append(
                        {
                            "name_col": header_map[name_col_stripped],
                            "x_col": header_map[x_col_stripped],
                            "y_col": header_map[y_col_stripped],
                            "h_col": header_map.get(h_col_stripped) if h_col_stripped else None,
                        }
                    )

        if not entity_slots:
            raise RuntimeError(
                "Simulation log header does not contain recognizable esmini "
                "entity columns (Entitity_Name / World_Position_X/Y)."
            )

        for row in reader:
            # Parse global timestamp once per row.
            try:
                t = float(row[time_col])
            except (ValueError, TypeError, KeyError):
                continue

            for slot in entity_slots:
                name_raw = row.get(slot["name_col"], "")
                entity_name = str(name_raw).strip()
                if not entity_name:
                    continue

                try:
                    x = float(row[slot["x_col"]])
                    y = float(row[slot["y_col"]])
                    h_val = row.get(slot["h_col"]) if slot["h_col"] else None
                    if h_val not in (None, ""):
                        h = float(h_val)
                    else:
                        h = 0.0
                except (ValueError, TypeError, KeyError):
                    # Skip this entity for this row if values are not usable.
                    continue

                position = type("Position", (), {"x": x, "y": y, "h": h})()

                if entity_name in dynamic_data:
                    positions, times = dynamic_data[entity_name]
                    positions.append(position)
                    times.append(t)
                else:
                    dynamic_data[entity_name] = ([position], [t])

        return dynamic_data
    
    def _load_parameter_declarations_outside_storyboard(self):
        """
        Extract parameter declarations, excluding any inside Storyboard.
        Args:
            None
        return: Dict of parameter name to value.
        """
        tree = ET.parse(self.file_path)
        root = tree.getroot()

        parameters = {}
        storyboard = root.find('.//Storyboard')
        all_parameters = root.findall('.//ParameterDeclaration')

        if storyboard is not None:
            storyboard_parameters = set(storyboard.findall('.//ParameterDeclaration'))
        else:
            storyboard_parameters = set()

        for param in all_parameters:
            if param not in storyboard_parameters:
                name = param.get('name')
                value = param.get('value')
                parameters[name] = value

        return parameters

    @staticmethod
    def _replace_parameters_in_content(content, parameters):
        """
        Replace all $param$ placeholders with actual parameter values.
        Args:
            content: XML content as a string.
            parameters: Dict of parameter name to value.
        return: Updated content string.
        """
        for name, value in parameters.items():
            placeholder = f'${name}'
            content = content.replace(placeholder, value)
        return content

    def _check_actors_defined(self, entity_names):
        """
        Check if storyboard entities have been defined.
        Args:
            entity_names: List of entities defined in the scenario.
        return: List of missing entity definitions.
        """
        missing_entity_definitions = []

        for story in self.scenario.storyboard.stories:
            for act in story.acts:
                for maneuvergroup in act.maneuvergroup:
                    actors = {actor.entity for actor in maneuvergroup.actors.actors if '$' not in actor.entity}

                    if len(actors.intersection(set(entity_names))) != len(actors):
                        missing_entity_definition = list(set(actors) - set(entity_names))
                        missing_entity_definitions.append(missing_entity_definition)

        missing_entity_definitions = [x for xs in missing_entity_definitions for x in xs]

        for entity in entity_names:
            try:
                initactions = self.scenario.storyboard.init.initactions[entity]
            except KeyError:
                continue

            for initaction in initactions:
                if 'AbsoluteSpeedAction' in str(type(initaction)) and not isinstance(initaction.speed, float):
                    missing_entity_definitions.append(entity)

        return list(set(missing_entity_definitions))

    def _get_entities(self):
        """
        Gather entity names.
        Args:
            None
        return: Dict of entity name to type (or None if unavailable).
        """
        # Prefer typed vehicle info when available, fall back to names only.
        entities = {}

        try:
            for scenario_object in self.scenario.entities.scenario_objects:
                entities[scenario_object.name] = scenario_object.entityobject.vehicle_type.name
            return entities
        except AttributeError:
            entity_list = [scenario_object.name for scenario_object in self.scenario.entities.scenario_objects]
            return dict.fromkeys(entity_list)

    def _get_initial_positions(self, entity_names):
        """
        Check if entity has init position and if entity is parked.
        Args:
            entity_names: List of entity names to inspect.
        return: (init_positions_dict, parked_entities_list, unresolved_no_xodr_list, unresolved_conversion_list)
        """
        # Position is taken from TeleportAction; parked if speed is ~0.
        init_positions = {}
        parked_entities = []
        unresolved_no_xodr = []
        unresolved_conversion = []

        xodr_path = self.get_xodr_path()
        has_valid_xodr = xodr_path is not None

        for entity in entity_names:
            try:
                initactions = self.scenario.storyboard.init.initactions[entity]
            except KeyError:
                continue

            for initaction in initactions:
                if 'TeleportAction' in str(type(initaction)):
                    if 'WorldPosition' in str(type(initaction.position)):
                        init_positions[entity] = (initaction.position.x, initaction.position.y)
                    elif 'LanePosition' in str(type(initaction.position)):
                        if has_valid_xodr:
                            world_position = self._resolve_lane_position_to_world(initaction.position)
                            if world_position is not None:
                                init_positions[entity] = world_position
                            else:
                                init_positions[entity] = ('-', '-')
                                unresolved_conversion.append(entity)
                        else:
                            init_positions[entity] = ('-', '-')
                            unresolved_no_xodr.append(entity)
                    else:
                        init_positions[entity] = ('-', '-')
                elif 'AbsoluteSpeedAction' in str(type(initaction)):
                    if isinstance(initaction.speed, float) and initaction.speed < 1e-6:
                        parked_entities.append(entity)

        return init_positions, parked_entities, list(set(unresolved_no_xodr)), list(set(unresolved_conversion))

    @staticmethod
    def _is_numeric_position(position_value):
        if not isinstance(position_value, tuple) or len(position_value) != 2:
            return False
        return all(isinstance(v, (int, float, np.floating)) for v in position_value)

    def _resolve_lane_position_to_world(self, lane_position):
        """Resolve OpenSCENARIO LanePosition to world XY using OpenDRIVE geometry."""
        xodr_path = self.get_xodr_path()
        if xodr_path is None:
            return None
        return self._xodr_resolver.resolve_lane_position_to_world(xodr_path, lane_position)

    @staticmethod
    def _get_identical_initposition_entities(init_positions):
        """
        Check for identical initial positions.
        Args:
            init_positions: Dict of entity name to (x, y).
        return: List of entity groups with identical positions.
        """
        # Detect duplicate positions by counting identical tuples.
        identical_position_entities = []

        valid_positions = {k: v for k, v in init_positions.items() if FileQualityChecker._is_numeric_position(v)}

        if len(set(valid_positions.values())) != len(valid_positions.values()):
            Counter(valid_positions.values()).items()
            duplicates = [
                (i, item, count)
                for i, (item, count) in enumerate(Counter(valid_positions.values()).items())
                if count > 1
            ]

            for idx, item, count in duplicates:
                idxs = [idx]
                current_idx = idx
                for _ in range(count - 1):
                    idx_new = current_idx + list(valid_positions.values())[current_idx + 1 :].index(item) + 1
                    idxs.append(idx_new)
                    current_idx = idx_new

                identical_position = [list(valid_positions.keys())[pos] for pos in idxs]
                identical_position_entities.append(identical_position)

        return identical_position_entities

    def _get_intersecting_entities(self, init_positions, filter_by_radius=True):
        """
        Check if entities intersect using initial positions and bounding boxes.
        Args:
            init_positions: Dict of entity name to (x, y).
            filter_by_radius: Whether to prefilter by max radius.
        return: List of intersecting entity pairs.
        """
        # Optional radius-based prefilter to reduce pairwise polygon checks.
        intersecting_entites = []

        valid_init_positions = {k: v for k, v in init_positions.items() if self._is_numeric_position(v)}

        polygons, max_entity_radius = self._get_entities_bbox(valid_init_positions)
        if len(polygons) > 1:
            if filter_by_radius:
                distances = sp.spatial.distance.cdist(
                    np.array(list(valid_init_positions.values())),
                    np.array(list(valid_init_positions.values()))
                )
                distances = np.triu(distances)

                possible_intersection_indices = np.where(
                    np.logical_and(distances < 2 * max_entity_radius, distances > 1e-6)
                )
                valid = possible_intersection_indices[0] != possible_intersection_indices[1]
                possible_intersection_indices_a = possible_intersection_indices[0][valid]
                possible_intersection_indices_b = possible_intersection_indices[1][valid]
            else:
                possible_intersection_indices_a, possible_intersection_indices_b = list(range(len(polygons)))

            for index_a, index_b in zip(possible_intersection_indices_a, possible_intersection_indices_b):
                intersection = polygons[index_a].intersection(polygons[index_b])
                if not intersection.is_empty:
                    entity_a = list(valid_init_positions.keys())[index_a]
                    entity_b = list(valid_init_positions.keys())[index_b]
                    intersecting_entites.append([entity_a, entity_b])

        return intersecting_entites

    def _get_entities_bbox(self, init_positions):
        """
        Get entities' corners and create polygons with them.
        Args:
            init_positions: Dict of entity name to (x, y).
        return: (polygons_list, max_entity_radius)
        """
        # Bounding boxes are defined in the scenario object geometry.
        polygons = []
        max_entity_radius = -np.inf

        for scenario_object in self.scenario.entities.scenario_objects:
            if scenario_object.name in init_positions.keys():
                init_position = init_positions[scenario_object.name]
                if self._is_numeric_position(init_position) and hasattr(scenario_object.entityobject, 'boundingbox'):
                    length = scenario_object.entityobject.boundingbox.boundingbox.length
                    width = scenario_object.entityobject.boundingbox.boundingbox.width

                    coords = (
                        (init_position[0] + length / 2, init_position[1] + width / 2),
                        (init_position[0] + length / 2, init_position[1] - width / 2),
                        (init_position[0] - length / 2, init_position[1] - width / 2),
                        (init_position[0] - length / 2, init_position[1] + width / 2),
                    )
                    polygon = shapely.Polygon(coords)
                    polygons.append(polygon)

                    radius = shapely.minimum_bounding_radius(polygon)
                    if radius > max_entity_radius:
                        max_entity_radius = radius

        return polygons, max_entity_radius

    def _get_added_and_removed_entities(self):
        """
        Look for add and remove events in every maneuver group.
        Args:
            None
        return: (added_entities_list, removed_entities_list)
        """
        # Events are inferred by name convention (Add_/Remove_).
        added_entities = []
        removed_entities = []

        for story in self.scenario.storyboard.stories:
            for act in story.acts:
                for maneuvergroup in act.maneuvergroup:
                    actors = [actor.entity for actor in maneuvergroup.actors.actors]
                    if len(actors) > 1:
                        logger.warning(
                            f"Multiple actors in maneuver group; applying add/remove events to all actors: {actors}"
                        )

                    for maneuver in maneuvergroup.maneuvers:
                        for event in maneuver.events:
                            for actor in actors:
                                if '$' in actor:
                                    continue
                                if 'Add_' in event.name:
                                    added_entities.append(actor)
                                elif 'Remove_' in event.name:
                                    removed_entities.append(actor)

        if len(set(added_entities)) != len(added_entities):
            logger.warning("Duplicate Add_ events detected for one or more entities.")
        if len(set(removed_entities)) != len(removed_entities):
            logger.warning("Duplicate Remove_ events detected for one or more entities.")

        return list(set(added_entities)), list(set(removed_entities))

    @staticmethod
    def _check_in_out_entities(init_positions, parked_entities, added_entities, removed_entities):
        """
        Check if initialized + added equals removed + parked.
        Args:
            init_positions: Dict of entity name to init position.
            parked_entities: List of entities considered parked.
            added_entities: List of entities added via events.
            removed_entities: List of entities removed via events.
        return: List of missing entities.
        """
        # The accounting should balance; otherwise report missing entities.
        if set(added_entities).intersection(set(list(init_positions.keys()))):
            logger.warning("Entities appear both in init positions and Add_ events.")
        if set(removed_entities).intersection(set(parked_entities)):
            logger.warning("Entities appear both in Remove_ events and parked entities.")

        missing_in = []

        if len(added_entities) + len(init_positions) - len(removed_entities) - len(parked_entities) != 0:
            all_entities = added_entities + list(init_positions.keys()) + removed_entities
            in_entities = added_entities + list(init_positions.keys())

            missing_in = list(set(all_entities) - set(in_entities))

        return missing_in

    @staticmethod
    def _build_dynamic_data_df(positions, times):
        """
        Build a dataframe of positions and times.
        Args:
            positions: List of position objects.
            times: List of timestamps.
        return: Pandas DataFrame with time, x, y, h.
        """
        # Extract x/y/h fields for vectorized downstream calculations.
        xs = []
        ys = []
        hs = []
        for position in positions:
            xs.append(position.x)
            ys.append(position.y)
            hs.append(position.h)

        df = pd.DataFrame(times, columns=['time'])
        df['x'] = xs
        df['y'] = ys
        df['h'] = hs

        return df

    @staticmethod
    def _calculate_acceleration_swimangle(df, threshold=0.5 / 3.6, rolling_window=20):
        """
        Calculate acceleration and swim angle at every time step.
        Args:
            df: DataFrame with time, x, y, h columns.
            threshold: Minimum speed threshold for filtering movement angle.
            rolling_window: Window size for rolling mean calculations.
        return: DataFrame with added speed, acceleration, and swimangle columns.
        """
        # Derived values are finite differences across the trajectory.
        dt = df['time'].diff().rolling(window=rolling_window, center=True).mean()
        dx = df['x'].diff().rolling(window=rolling_window, center=True).mean()
        dy = df['y'].diff().rolling(window=rolling_window, center=True).mean()
        
        df['speed'] = (np.sqrt(dx**2 + dy**2) / dt )
        df['acceleration'] = df['speed'].diff() / dt
        
        df['movement_angle'] = np.arctan2(dy, dx)
        df['movement_angle'] = df['movement_angle'].bfill()
        
        mask = (df.speed > threshold)
        
        df['filtered_movement_angle'] = df['movement_angle'].where(mask).ffill().bfill()
        df['swimangle'] = df['h'].fillna(0) - df['filtered_movement_angle']
        
        df['swimangle'] = ((df['swimangle'] + np.pi) % (2 * np.pi)) - np.pi
        
        return df
    
    def create_single_report(self, title, out_path):
        """
        Generate a PDF report for the current scenario.
        Args:
            title: Title for the report.
            out_path: Output directory for the PDF.
        """
        create_report_single(self, title, out_path)
        if self.print_log:
            logger.info(f'Report created: {out_path}')

    def create_csv(self, name, out_path):
        """
        Write a CSV report with metadata, file errors, and dynamics.
        Args:
            name: Base filename for the CSV.
            out_path: Output directory for the CSV.
        """
        csv_file = out_path / Path(name + '.csv')
        with open(csv_file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(['scenario_file', self.file_path])
            writer.writerow(['xml_loadable', self.xml_loadable])
            writer.writerow(['xsd_valid', self.xsd_valid])
            writer.writerow(['version', self.version.replace('-', '.') if self.version else self.version])
            writer.writerow(['author', self.author])
            writer.writerow(['date', self.date])
            writer.writerow(['simulation_status', self.simulation_status])
            for road_user, count in self.road_user_counts.items():
                writer.writerow([road_user, count])
            
            writer.writerow([])
            writer.writerow(['file_errors'])
            writer.writerow(['missing_entity_definitions'])
            for missing_entity_definition in self.file_errors[0]:
                writer.writerow([missing_entity_definition])
            writer.writerow(['identical_initposition_entities'])
            for identical_initposition_entity in self.file_errors[1]:
                writer.writerow([identical_initposition_entity])
            writer.writerow(['intersecting_entities'])
            for intersecting_entity in self.file_errors[2]:
                writer.writerow([intersecting_entity])
            writer.writerow(['missing_in'])
            for missing_in in self.file_errors[3]:
                writer.writerow([missing_in])

            writer.writerow(['position_resolution_warnings'])
            for warning in self.position_resolution_warnings:
                writer.writerow([warning])
            
            writer.writerow([])
            writer.writerow(['dynamic_errors'])
            writer.writerow(['acceleration_errors'])
            for acceleration_error in (self.dynamic_errors or ([], [], [], []))[0]:
                writer.writerow([acceleration_error])
            writer.writerow(['acceleration_warnings'])
            for acceleration_warning in (self.dynamic_errors or ([], [], [], []))[1]:
                writer.writerow([acceleration_warning])
            writer.writerow(['swimangle_errors'])
            for swimangle_error in (self.dynamic_errors or ([], [], [], []))[2]:
                writer.writerow([swimangle_error])
            writer.writerow(['swimangle_warnings'])
            for swimangle_warning in (self.dynamic_errors or ([], [], [], []))[3]:
                writer.writerow([swimangle_warning])
                
        if self.print_log:
            logger.info(f'CSV report created at {csv_file}')
        return


@app.command("quality_check_single")
def quality_check_single(
    file_path: Path = typer.Option(...),
    out_path: Path = typer.Option(Path("reports/single_reports/")),
    schema_path: Path = typer.Option(DEFAULT_SCHEMA_PATH, help="Path to the schema files"),
    esmini_path: Path = typer.Option(None, help="Path to the esmini executable. If given, simulation is used to assess dynamics"),
    out_pdf: bool = typer.Option(False),
    out_csv: bool = typer.Option(False),
    print_log: bool = typer.Option(False)): 
    """
    Check a single scenario and optionally output PDF/CSV reports.
    Args:
        file_path: Path to the scenario file.
        out_path: Output directory for reports.
        schema_path: Path to schema files.
        out_pdf: Whether to create a PDF report.
        out_csv: Whether to create a CSV report.
        print_log: Whether to emit log output.
    return: FileQualityChecker instance.
    """
    
    # Run analysis for one file.
    fqc = FileQualityChecker(file_path, schema_path, esmini_path, print_log)
    
    # Create report (pdf and/or csv).
    if out_pdf:
        report_title = 'Summary of ' + fqc.file_path.name
        fqc.create_single_report(report_title, out_path)
    if out_csv:
        fqc.create_csv(fqc.file_path.name, out_path)
    if print_log:
        logger.info(f"Analysis completed for {str(file_path)}.")
    return fqc
    
    
@app.command("quality_check_multiple")
def quality_check_multiple(
    files_path: Path = typer.Option(...),
    out_path: Path = typer.Option(Path("reports/")),
    schema_path: Path = typer.Option(DEFAULT_SCHEMA_PATH, help="Path to the schema files"),
    esmini_path: Path = typer.Option(None, help="Path to the esmini executable. If given, simulation is used to assess dynamics"),
    single: bool = typer.Option(False),
    aggregated: bool = typer.Option(False),
    out_pdf: bool = typer.Option(False),
    out_csv: bool = typer.Option(False),
    print_log: bool = typer.Option(False)): 
    """
    Check multiple scenarios and optionally output reports.
    Args:
        files_path: Directory containing .xosc files.
        out_path: Output directory for reports.
        schema_path: Path to schema files.
        esmini_path: Path to the esmini executable.
        single: Whether to generate single reports per file.
        aggregated: Whether to generate an aggregated report.
        out_pdf: Whether to create a PDF report.
        out_csv: Whether to create a CSV report.
        print_log: Whether to emit log output.
    return: Aggregated summary list or -1 on invalid input.
    """
    if print_log:
        logger.info(f'Starting analysis of all .xosc files in {files_path}')
    
    # Ensure we have a directory to scan for .xosc files.
    if not files_path.is_dir():
        logger.error('Files path is not a directory')
        return -1
        
    # Collect per-file checkers when aggregation is requested.
    aggregated_checkers = [] if aggregated else None
    for file in files_path.glob('*.xosc'):
        if single:
            Path(out_path / Path('single_reports/')).mkdir(parents=True, exist_ok=True)
            checker = quality_check_single(file, out_path / Path('single_reports/'), schema_path, esmini_path, out_pdf, out_csv)
        else:
            checker = quality_check_single(file, out_path / Path('single_reports/'), schema_path, esmini_path, False, False, False)

        if aggregated:
            aggregated_checkers.append(checker)
    
    if aggregated:
        title = 'Aggregated report'
        information_summary = [list(checker.to_summary_row()) for checker in aggregated_checkers]

        # create report (pdf and/or csv)
        if out_pdf:
            create_report_multiple(title, information_summary, out_path, print_log)
        if out_csv:
            # Prepend a header row for CSV export.
            information_summary.insert(0, ['scenario_file', 'xml_loadable', 'xsd_valid', 'simulation_status', 'n_file_errors', 'n_dynamic_errors'])
            csv_file = out_path / Path('aggregate_data.csv')
            with open(csv_file, mode="w", newline="") as file:
                writer = csv.writer(file)
                writer.writerows(information_summary)
            if print_log:
                logger.info(f'CSV report created at {csv_file}')
        if print_log:
            logger.info(f'Analysis completed for all .xosc files in {files_path}.')
        return information_summary
