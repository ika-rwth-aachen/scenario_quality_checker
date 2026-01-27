
from collections import Counter
import csv
from datetime import datetime
from loguru import logger
import numpy as np
import os
import pandas as pd
from pathlib import Path
import tempfile
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

app = typer.Typer()   


class FileQualityChecker:
    def __init__(self, scenario_path, schema_path, print_log=False):
        """
        Initialize the checker and run the full validation pipeline.
        Args:
            scenario_path: Path to the .xosc scenario file.
            schema_path: Path to the directory with XSD schemas.
            print_log: Whether to emit log output.
        """
        self.file_path = scenario_path
        self.print_log = print_log
        
        self.xml_loadable = False
        self.xsd_valid = False
        self.version = None
        self.author = None
        self.date = None
        self.scenario = None
        self.road_user_counts = Counter()
        self.file_errors = ([], [], [], [])
        self.dynamic_errors = None
        
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
        return: Tuple of (file_path, xml_loadable, xsd_valid, n_file_errors, n_dynamic_errors)
        """
        # Keep values stable even when earlier stages failed.
        if not self.xml_loadable:
            return (self.file_path, False, False, '-', '-')

        if not self.xsd_valid:
            return (self.file_path, True, False, '-', '-')

        if self.scenario is None:
            return (self.file_path, True, True, '-', '-')

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

        return (self.file_path, True, True, file_error_count, dynamic_error_count)

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
        
        # Schema files exist for v1.x only; v2+ is treated as unsupported here.
        if int(revMajor) < 2:
            file = Path('OpenSCENARIO_' + xsd_version + '.xsd')
            schema_file = schema_path / file
        else: 
            # print('File version ' + xsd_version + ' is NOT known')
            return (False, xsd_version)
        
        if not os.path.isfile(schema_file):
            # print('Schema file for version ' + xsd_version + ' is NOT available')
            return (False, xsd_version)
        
        xsd = xmlschema.XMLSchema(schema_file)

        return (xsd.is_valid(self.file_path), xsd_version)     
        
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
            self._clean_up_temp_file(temp_file)

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

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xosc', delete=False, encoding='utf-8') as temp:
            temp.write(updated_content)
            return Path(temp.name)

    def _clean_up_temp_file(self, temp_file):
        """
        Delete the temporary file after processing.
        Args:
            temp_file: Path to the temporary file.
        """
        temp_path = Path(temp_file)
        if temp_path.exists():
            temp_path.unlink()
        return
    
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
        missing_entity_definitions = self._are_actors_defined(entity_names)

        init_positions, parked_entities = self._get_initial_positions(entity_names)
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
            None
        return: Dict mapping entity name to (positions, times).
        """
        dynamic_data = {}
        for story in self.scenario.storyboard.stories:
            for act in story.acts:
                for maneuvergroup in act.maneuvergroup:
                    actors = [actor.entity for actor in maneuvergroup.actors.actors]
                    actor = actors[0] # theres only one actor per maneuvergroup as of now
                    
                    for maneuver in maneuvergroup.maneuvers:
                        for event in maneuver.events:
                            if 'Trajectory_event_' in event.name:
                                for action in event.action: # theres only one action per event
                                    times = action.action.trajectory.shapes.time
                                    positions = action.action.trajectory.shapes.positions
                                    dynamic_data[actor] = (positions, times)
        
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

    def _are_actors_defined(self, entity_names):
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
        return: (init_positions_dict, parked_entities_list)
        """
        # Position is taken from TeleportAction; parked if speed is ~0.
        init_positions = {}
        parked_entities = []
        for entity in entity_names:
            try:
                initactions = self.scenario.storyboard.init.initactions[entity]
            except KeyError:
                continue

            for initaction in initactions:
                if 'TeleportAction' in str(type(initaction)):
                    if 'WorldPosition' in str(type(initaction.position)):
                        init_positions[entity] = (initaction.position.x, initaction.position.y)
                    else:
                        init_positions[entity] = ('-', '-')
                elif 'AbsoluteSpeedAction' in str(type(initaction)):
                    if isinstance(initaction.speed, float) and initaction.speed < 1e-6:
                        parked_entities.append(entity)

        return init_positions, parked_entities

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

        if len(set(init_positions.values())) != len(init_positions.values()):
            Counter(init_positions.values()).items()
            duplicates = [
                (i, item, count)
                for i, (item, count) in enumerate(Counter(init_positions.values()).items())
                if count > 1
            ]

            for idx, item, count in duplicates:
                idxs = [idx]
                current_idx = idx
                for _ in range(count - 1):
                    idx_new = current_idx + list(init_positions.values())[current_idx + 1 :].index(item) + 1
                    idxs.append(idx_new)
                    current_idx = idx_new

                identical_position = [list(init_positions.keys())[pos] for pos in idxs]
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

        polygons, max_entity_radius = self._get_entities_bbox(init_positions)
        if len(polygons) > 1:
            if filter_by_radius:
                distances = sp.spatial.distance.cdist(
                    np.array(list(init_positions.values())),
                    np.array(list(init_positions.values()))
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
                    entity_a = list(init_positions.keys())[index_a]
                    entity_b = list(init_positions.keys())[index_b]
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
                if init_position != ('-', '-') and hasattr(scenario_object.entityobject, 'boundingbox'):
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
    def _calculate_acceleration_swimangle(df):
        """
        Calculate acceleration and swim angle at every time step.
        Args:
            df: DataFrame with time, x, y, h columns.
        return: DataFrame with added speed, acceleration, and swimangle columns.
        """
        # Derived values are finite differences across the trajectory.
        steps = 1

        t_change = df.time[steps:].reset_index(drop=True) - df.time[:-steps].reset_index(drop=True)

        x_change = df.x[steps:].reset_index(drop=True) - df.x[:-steps].reset_index(drop=True)
        y_change = df.y[steps:].reset_index(drop=True) - df.y[:-steps].reset_index(drop=True)
        xy_change = np.sqrt(x_change**2 + y_change**2)

        speed = xy_change / t_change
        df['speed'] = speed

        speed_change = df.speed[steps:].reset_index(drop=True) - df.speed[:-steps].reset_index(drop=True)

        acceleration = speed_change / t_change
        df['acceleration'] = acceleration

        df['movement_angle'] = np.arctan2(y_change, x_change)
        df.movement_angle = df.movement_angle.mod(2 * np.pi)
        df['swimangle'] = df.h - df.movement_angle

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
            writer.writerow(['version', self.version])
            writer.writerow(['author', self.author])
            writer.writerow(['date', self.date])
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
    schema_path: Path = typer.Option(Path("schemas/"), help="Path to the schema files"),
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
    fqc = FileQualityChecker(file_path, schema_path, print_log)
    
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
    schema_path: Path = typer.Option(Path("schemas/"), help="Path to the schema files"),
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
            Path(out_path / Path('single_reports/')).mkdir(exist_ok=True)
            checker = quality_check_single(file, out_path / Path('single_reports/'), schema_path, out_pdf, out_csv)
        else:
            checker = quality_check_single(file, out_path / Path('single_reports/'), schema_path, False, False, False)

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
            information_summary.insert(0, ['scenario_file', 'xml_loadable', 'xsd_valid', 'n_file_errors', 'n_dynamic_errors'])
            csv_file = out_path / Path('aggregate_data.csv')
            with open(csv_file, mode="w", newline="") as file:
                writer = csv.writer(file)
                writer.writerows(information_summary)
            if print_log:
                logger.info(f'CSV report created at {csv_file}')
        if print_log:
            logger.info(f'Analysis completed for all .xosc files in {files_path}.')
        return information_summary
