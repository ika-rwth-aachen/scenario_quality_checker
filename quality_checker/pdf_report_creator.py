
from loguru import logger
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from pathlib import Path
import tempfile

from .pdf import *

from .config import Config

ERROR_THRESHOLDS = {
    'acceleration': Config.ACCELERATION_ERROR_THRESHOLD,
    'swimangle': Config.SWIMANGLE_ERROR_THRESHOLD}

WARNING_THRESHOLDS = {
    'acceleration': Config.ACCELERATION_WARNING_THRESHOLD,
    'swimangle': Config.SWIMANGLE_WARNING_THRESHOLD}


def create_report_single(checker, title, out_path):
    """
    creates a pdf report summarizing passed and failed tests and other warnings
    """
    title_size = 12
    title_separation = -5
    subtitle_size = 8
    subtitle_separation = -4
    
    pdf = PDF(title)
    pdf.add_page()

    scenario_path = Path(checker.file_path)
    pdf.create_textbox('Scenario file: ' + scenario_path.name, relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})

    if checker.xml_loadable:
        
        if checker.xsd_valid:
            author = 'Scenario author: '
            author += checker.author if checker.author else '-'
            pdf.create_textbox(author, relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
            
            date = 'Scenario creation date: '
            date += checker.date if checker.date else '-'
            pdf.create_textbox(date, relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
            
            version = 'OpenSCENARIO version: '
            version += checker.version if checker.version else '-'
            pdf.create_textbox(version, relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
            
            if checker.scenario is not None:
                
                n_roadusers = 'Road users in scenario: '
                road_users = checker.road_user_counts or {}
                n_total = road_users.get('total', 0)
                n_roadusers += str(n_total)
                pdf.create_textbox(n_roadusers, relative_position=[0, title_separation+8], font={"name": "Arial", "type": "B", "size": title_size})
                
                for RU_type, count in road_users.items():
                    if RU_type != 'total' and RU_type is not None:
                        pdf.create_textbox('     ' + RU_type + 's in scenario: ' + str(count), relative_position=[0, subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                
                dynamic_errors = checker.dynamic_errors or ([], [], [], [])
                acceleration_errors, acceleration_warnings, swimangle_errors, swimangle_warnings = dynamic_errors
                analyzed_dynamics = {
                    "acceleration_errors": acceleration_errors,
                    "acceleration_warnings": acceleration_warnings,
                    "swimangle_errors": swimangle_errors,
                    "swimangle_warnings": swimangle_warnings,
                }
                temp_dir = tempfile.TemporaryDirectory()
                temp_dir_path = Path(temp_dir.name)
                plot_dynamics(checker, analyzed_dynamics, output_dir=temp_dir_path)

                try:
                    pdf.create_image(temp_dir_path / 'vehicle_paths.png', relative_position=[85, -27], size=(int(588/6), int(432/6)))
                except Exception:
                    pass

                pdf.create_textbox('Scenario issues', relative_position=[0, title_separation+2], font={"name": "Arial", "type": "B", "size": title_size})
                file_errors = checker.file_errors or ([], [], [], [])
                if np.sum([len(file_error) for file_error in file_errors]) == 0:
                    pdf.create_textbox(text="4", relative_position=[0, title_separation], font={"name": "zapfdingbats", "type": "","size": title_size-2})
                    pdf.create_textbox('     No file issues: ', relative_position=[0, 2*title_separation], font={"name": "Arial", "type": "B", "size": title_size-2})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                       font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No faulty entity definitions', relative_position=[0, 2*subtitle_separation], 
                                       font={"name": "Arial", "type": "B", "size": subtitle_size})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                       font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No identical initial positions', relative_position=[0, 2*subtitle_separation], 
                                       font={"name": "Arial", "type": "B", "size": subtitle_size})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                       font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No intersecting entities', relative_position=[0, 2*subtitle_separation], 
                                       font={"name": "Arial", "type": "B", "size": subtitle_size})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                       font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No missing adds/inits', relative_position=[0, 2*subtitle_separation], 
                                       font={"name": "Arial", "type": "B", "size": subtitle_size})
                else:
                    missing_entity_definitions, identical_initposition_entities, intersecting_entities, missing_in = file_errors
                    pdf.create_textbox(text="8", relative_position=[0, title_separation], 
                                       font={"name": "zapfdingbats", "type": "","size": title_size-2}, color=Config.ERROR_COLOR)
                    pdf.create_textbox('     File issues', relative_position=[0, 2*title_separation], 
                                       font={"name": "Arial", "type": "B", "size": title_size-2}, color=Config.ERROR_COLOR)
                    if len(missing_entity_definitions) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
                        pdf.create_textbox('          Faulty entity definitions: ' + str(', '.join(missing_entity_definitions)), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No faulty entity definitions', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                    if len(identical_initposition_entities) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
                        if len(identical_initposition_entities) == 1:
                            identical_initposition_entities = identical_initposition_entities[0]
                            
                            pdf.create_textbox('          Identical initial positions: ' + str(', '.join(identical_initposition_entities)), relative_position=[0, 2*subtitle_separation], 
                                            font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                        else:
                            identical_initposition_entities = [str(tuple(element)).replace("'", "") for element in identical_initposition_entities]
                            
                            pdf.create_textbox('          Identical initial positions: ' + str(', '.join(identical_initposition_entities)), relative_position=[0, 2*subtitle_separation], 
                                            font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No identical initial positions', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                    if len(intersecting_entities) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
                        if len(intersecting_entities) == 1:
                            intersecting_entities = intersecting_entities[0]
                            pdf.create_textbox('          Intersecting entities: ' + str(', '.join(intersecting_entities)), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                        else:
                            intersecting_entities = [str(tuple(element)).replace("'", "") for element in intersecting_entities]
                            pdf.create_textbox('          Intersecting entities: ' + str(', '.join(intersecting_entities)), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No intersecting entities', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                    if len(missing_in) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
                        pdf.create_textbox('          Missing add/init: ' + str(', '.join(missing_in)), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No missing adds/inits', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                # pdf.create_textbox('Dynamic', relative_position=[0, 0], font={"name": "Arial", "type": "B", "size": title_size})
                if np.sum([len(dynamic_error) for dynamic_error in dynamic_errors]) == 0:
                    pdf.create_textbox(text="4", relative_position=[0, title_separation+2], font={"name": "zapfdingbats", "type": "","size": title_size-2})
                    pdf.create_textbox('     No dynamic issues', relative_position=[0, 2*title_separation], font={"name": "Arial", "type": "B", "size": title_size-2})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No acceleration errors', relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "B", "size": subtitle_size})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No swim angle errors', relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "B", "size": subtitle_size})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No acceleration warnings', relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "B", "size": subtitle_size})
                    pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                    pdf.create_textbox('          No swim angle warnings', relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "B", "size": subtitle_size})
                else:
                    pdf.create_textbox(text="8", relative_position=[0, title_separation+1], 
                                       font={"name": "zapfdingbats", "type": "","size": title_size-2}, color=Config.ERROR_COLOR)
                    pdf.create_textbox('     Dynamic issues', relative_position=[0, 2*title_separation], 
                                       font={"name": "Arial", "type": "B", "size": title_size-2}, color=Config.ERROR_COLOR)
                    if len(acceleration_errors) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
                        pdf.create_textbox('          Acceleration errors: ' + str(acceleration_errors), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No acceleration errors', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                    if len(swimangle_errors) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
                        pdf.create_textbox('          Swim angle errors: ' + str(swimangle_errors), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.ERROR_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No swim angle errors', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                    if len(acceleration_warnings) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.WARNING_COLOR)
                        pdf.create_textbox('          Acceleration warnings: ' + str(acceleration_warnings), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.WARNING_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No acceleration warnings', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})
                    
                    if len(swimangle_warnings) > 0:
                        pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.WARNING_COLOR)
                        pdf.create_textbox('          Swim angle warnings: ' + str(swimangle_warnings), relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size}, color=Config.WARNING_COLOR)
                    else:
                        pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], 
                                           font={"name": "zapfdingbats", "type": "","size": subtitle_size})
                        pdf.create_textbox('          No swim angle warnings', relative_position=[0, 2*subtitle_separation], 
                                           font={"name": "Arial", "type": "B", "size": subtitle_size})

                try:
                    pdf.create_image(temp_dir_path / 'speed_plot.png', relative_position=[85, -12], size=(int(588/6), int(432/6)))
                    pdf.create_image(temp_dir_path / 'acceleration_plot.png', relative_position=[-10, 60], size=(int(588/6), int(432/6)))
                    pdf.create_image(temp_dir_path / 'swimangle_plot.png', relative_position=[85, 60], size=(int(588/6), int(432/6)))
                    pdf.create_textbox("Note: Paths for all road users are plotted, but speed, acceleration, and swim angle are shown only for the most relevant ones.",
                                   relative_position=[0, 135], font={"name": "Arial", "type": "", "size": subtitle_size})
                except Exception:
                    pdf.create_textbox("Note: Graphs could not be generated because envelope does not contain any stories.", 
                                    relative_position=[0, 135], font={"name": "Arial", "type": "", "size": subtitle_size})

                temp_dir.cleanup()
                    
                report_file = Path(scenario_path.stem + '.pdf')
                out = out_path / report_file
                pdf.output(out)
            else:
                pdf.create_textbox('Scenario could not be loaded', relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
                out = out_path / Path(scenario_path.stem + '.pdf')
                pdf.output(out)
        else:
            pdf.create_textbox('File is not in XSD format', relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
            out = out_path / Path(scenario_path.stem + '.pdf')
            pdf.output(out)
    else:
        pdf.create_textbox('File is not in XML format', relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
        out = out_path / Path(scenario_path.stem + '.pdf')
        pdf.output(out)
        

def add_error_warning_lines(ax, variable):
    """
    adds horizontal lines to a plot indicating error and warning thresholds
    """
    xmin, xmax = ax.get_xlim()
    error_threshold = ERROR_THRESHOLDS[variable]
    warning_threshold = WARNING_THRESHOLDS[variable]
    
    ax.hlines(+error_threshold, xmin=xmin, xmax=xmax, 
                            linestyle=(0, (5, 10)), colors=tuple(np.array(Config.ERROR_COLOR)/255))
    ax.hlines(+warning_threshold, xmin=xmin, xmax=xmax, 
                            linestyle=(0, (5, 10)), colors=tuple(np.array(Config.WARNING_COLOR)/255))
    ax.hlines(-warning_threshold, xmin=xmin, xmax=xmax, 
                            linestyle=(0, (5, 10)), colors=tuple(np.array(Config.WARNING_COLOR)/255))
    ax.hlines(-error_threshold, xmin=xmin, xmax=xmax, 
                            linestyle=(0, (5, 10)), colors=tuple(np.array(Config.ERROR_COLOR)/255))
    ax.text(0.15, 0.95, 'Error', transform=ax.transAxes, fontsize=10, verticalalignment='top', color=tuple(np.array(Config.ERROR_COLOR)/255))
    ax.text(0.13, 0.72, 'Warning', transform=ax.transAxes, fontsize=10, verticalalignment='top', color=tuple(np.array(Config.WARNING_COLOR)/255))
    ax.text(0.13, 0.32, 'Warning', transform=ax.transAxes, fontsize=10, verticalalignment='top', color=tuple(np.array(Config.WARNING_COLOR)/255))
    ax.text(0.15, 0.09, 'Error', transform=ax.transAxes, fontsize=10, verticalalignment='top', color=tuple(np.array(Config.ERROR_COLOR)/255))

    ax.legend()


def plot_dynamics(checker, analyzed_dynamics, n_plot_entities=5, output_dir=None):
    ylabel_speed = 'Speed [m/s]'
    ylabel_acceleration = 'Acceleration [m/s2]'
    ylabel_swimangle = 'Swim angle [rad]'
    xlabel = 'Time [s]'
    output_dir = Path(output_dir) if output_dir else Path('.')
    
    dynamic_data = checker._get_dynamic_data()
    if len(dynamic_data) == 0:
        return
    plot_vehicle_paths(dynamic_data, checker, save=True, output_dir=output_dir)
    
    speed_plot = plt.figure()
    speed_ax = speed_plot.add_subplot(111)
    acceleration_plot = plt.figure()
    acceleration_ax = acceleration_plot.add_subplot(111)
    swimangle_plot = plt.figure()
    swimangle_ax = swimangle_plot.add_subplot(111)
    
    for entity_name in dynamic_data.keys():
        positions, times = dynamic_data[entity_name]
        df = checker._build_dynamic_data_df(positions, times)
        df = checker._calculate_acceleration_swimangle(df)

        if 'ego' in entity_name:
            plot_variable(speed_ax, df, 'speed', entity_name, xlabel, ylabel_speed, save=False)
            plot_variable(acceleration_ax, df, 'acceleration', entity_name, xlabel, ylabel_acceleration, save=False)
            plot_variable(swimangle_ax, df, 'swimangle', entity_name, xlabel, ylabel_swimangle, save=False)
        else:
            if np.any(np.abs(df.acceleration) > Config.ACCELERATION_ERROR_THRESHOLD):
                plot_variable(speed_ax, df, 'speed', entity_name, xlabel, ylabel_speed, save=False)
                plot_variable(acceleration_ax, df, 'acceleration', entity_name, xlabel, ylabel_acceleration, save=False)
            elif np.any(np.abs(df.acceleration) > Config.ACCELERATION_WARNING_THRESHOLD):
                plot_variable(speed_ax, df, 'speed', entity_name, xlabel, ylabel_speed, save=False)
                plot_variable(acceleration_ax, df, 'acceleration', entity_name, xlabel, ylabel_acceleration, save=False)

            if np.any(np.abs(df.swimangle) > Config.SWIMANGLE_ERROR_THRESHOLD):
                plot_variable(swimangle_ax, df, 'swimangle', entity_name, xlabel, ylabel_swimangle, save=False)
            elif np.any(np.abs(df.swimangle) > Config.SWIMANGLE_WARNING_THRESHOLD):
                plot_variable(swimangle_ax, df, 'swimangle', entity_name, xlabel, ylabel_swimangle, save=False)
        mpl.pyplot.close()
        
    speed_ax.set_title('Speed over time')
    select_and_plot_extra_entities(dynamic_data, 'speed', speed_ax, analyzed_dynamics["acceleration_errors"], analyzed_dynamics["acceleration_warnings"], n_plot_entities, checker, xlabel=xlabel, ylabel=ylabel_speed, save=False)
    speed_plot.savefig(output_dir / 'speed_plot.png')
    
    # Acceleration
    select_and_plot_extra_entities(dynamic_data, 'acceleration', acceleration_ax, analyzed_dynamics["acceleration_errors"], analyzed_dynamics["acceleration_warnings"], n_plot_entities, checker, xlabel=xlabel, ylabel=ylabel_acceleration, save=False)
    acceleration_ax.set_title('Acceleration over time')
    add_error_warning_lines(acceleration_ax, 'acceleration')
    acceleration_plot.savefig(output_dir / 'acceleration_plot.png')
    
    # Swim angle
    select_and_plot_extra_entities(dynamic_data, 'swimangle', swimangle_ax, analyzed_dynamics["swimangle_errors"], analyzed_dynamics["swimangle_warnings"], n_plot_entities, checker, xlabel=xlabel, ylabel=ylabel_swimangle, save=False)
    swimangle_ax.set_title('Swim angle over time')
    add_error_warning_lines(swimangle_ax, 'swimangle')
    swimangle_plot.savefig(output_dir / 'swimangle_plot.png')


def create_report_multiple(title, file_information, out_path, print_log=False):
    """
    creates a pdf report summarizing passed and failed tests and other warnings
    """
    title_size = 12
    title_separation = -5
    subtitle_size = 8
    subtitle_separation = -4
    
    pdf = PDF(title)
    pdf.add_page()

    pdf.create_textbox('Tests', relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": title_size})
    pdf.create_textbox(
        ' ' * 10 + 'Scenario files'
        + ' ' * 55 + 'XML loadable'
        + ' ' * 12 + 'XSD valid'
        + ' ' * 11 + 'File issues'
        + ' ' * 8 + 'Dynamic issues', relative_position=[0, title_separation], font={"name": "Arial", "type": "B", "size": subtitle_size})
    
    for file in file_information:
        if file[1] and file[2] and file[3] == 0 and file[4] == 0:
            pdf.create_textbox(text="     4", relative_position=[0, subtitle_separation], font={"name": "zapfdingbats", "type": "","size": subtitle_size})
            pdf.create_textbox('          ' + file[0].parts[-1], relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 100) + "4" * int(file[1]), relative_position=[0, 2*subtitle_separation], font={"name": "zapfdingbats", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 130) + "4" * int(file[2]), relative_position=[0, 2*subtitle_separation], font={"name": "zapfdingbats", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 160) + str('0'), relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 190) + str('0'), relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "", "size": subtitle_size})
        else:
            pdf.create_textbox(text="     8", relative_position=[0, subtitle_separation], font={"name": "zapfdingbats", "type": "","size": subtitle_size}, color=Config.ERROR_COLOR)
            pdf.create_textbox(' ' * 10 + file[0].parts[-1], relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "","size": subtitle_size})
            pdf.create_textbox((" " * 100) + ("4" * int(file[1])) + ("8" * (1-int(file[1]))), relative_position=[0, 2*subtitle_separation], font={"name": "zapfdingbats", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 130) + ("4" * int(file[2])) + ("8" * (1-int(file[2]))), relative_position=[0, 2*subtitle_separation], font={"name": "zapfdingbats", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 160) + str(file[3]), relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "", "size": subtitle_size})
            pdf.create_textbox((" " * 190) + str(file[4]), relative_position=[0, 2*subtitle_separation], font={"name": "Arial", "type": "", "size": subtitle_size})
        pdf.create_line(color=(0, 0, 0), relative_position=[0, -2])

    out = out_path / Path('aggregate_report.pdf' )
    pdf.output(out)
    if print_log:
        logger.info(f'Report created: {out}')


def plot_variable(ax, df, variable, entity_name, xlabel, ylabel, save=False):
    if 'ego' in entity_name:
        ax.plot(df.time, df.loc[:, variable], label=entity_name, color=Config.EGO_COLORMAP(255), zorder=999)
    else:
        ax.plot(df.time, df.loc[:, variable], label=entity_name, color=Config.OTHER_COLORMAP(255), zorder=-1)
    # plt.title(str(variable) + ' over time for entity ' + entity_name)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if save:
        plt.savefig(str(variable) + '_' + entity_name + '.png')
    mpl.pyplot.close()


def plot_fading_line(ax, df, label, zorder, segment_size=10, arrow_size=2, colormap=mpl.colormaps['Blues']):
    """
    Plots a line that fades from light to dark.
    """
    n_segments = int(df.shape[0] / segment_size)
    
    for segment in range(n_segments - arrow_size + 1):
        ax.plot(
            df[segment * segment_size:(segment+1)*segment_size+1].x, 
            df[segment * segment_size:(segment+1)*segment_size+1].y,
            label=label,
            c=colormap(int((255/n_segments))*segment),
            zorder=zorder
        )
    mpl.pyplot.close()


def plot_vehicle_paths(dynamic_data, checker, segment_size=10, arrow_size=1, save=True, output_dir=None):
    """
    Plots the paths of vehicles over time.
    """
    output_dir = Path(output_dir) if output_dir else Path('.')
    paths_plot = plt.figure()
    paths_ax = paths_plot.add_subplot(111)
    
    for entity_name in dynamic_data.keys():
        positions, times = dynamic_data[entity_name]
        df = checker._build_dynamic_data_df(positions, times)
        df = checker._calculate_acceleration_swimangle(df)

        if df.shape[0] < arrow_size * segment_size:
            continue
        
        if 'ego' in entity_name:
            plot_fading_line(paths_ax, df, label='ego vehicle', segment_size=segment_size, arrow_size=arrow_size, colormap=Config.EGO_COLORMAP, zorder=999)
            paths_ax.arrow(df.iloc[-arrow_size*segment_size].x, df.iloc[-arrow_size*segment_size].y, 
                           df.iloc[-1].x - df.iloc[-arrow_size*segment_size].x, df.iloc[-1].y - df.iloc[-arrow_size*segment_size].y, 
                           head_width=2, head_length=5, length_includes_head=True, color=Config.EGO_COLORMAP(255), zorder=999)
        else:
            plot_fading_line(paths_ax, df, label='other', segment_size=10, arrow_size=arrow_size, colormap=Config.OTHER_COLORMAP, zorder=-1)
            paths_ax.arrow(df.iloc[-arrow_size*segment_size].x, df.iloc[-arrow_size*segment_size].y, 
                           df.iloc[-1].x - df.iloc[-arrow_size*segment_size].x, df.iloc[-1].y - df.iloc[-arrow_size*segment_size].y, 
                           head_width=2, head_length=5, length_includes_head=True, color=Config.OTHER_COLORMAP(255), zorder=-1)

    legend_elements = [Line2D([0], [0], color=Config.EGO_COLORMAP(255), label='ego vehicle'),
                    Line2D([0], [0], color=Config.OTHER_COLORMAP(255), label='other vehicles')]
    paths_ax.legend(handles=legend_elements)
    paths_ax.set_xlabel('X [m]')
    paths_ax.set_ylabel('Y [m]')
    paths_ax.set_title('Vehicle paths')

    if save:
        paths_plot.savefig(output_dir / 'vehicle_paths.png')
    mpl.pyplot.close()


def select_and_plot_extra_entities(dynamic_data, variable, ax, entities_errors, entities_warnings, n_plot_entities, checker, xlabel, ylabel, save=False):
    """
    selects extra entities to plot if not enough entities with errors or warnings
    """
    plot_entities = [entity_name for entity_name in list(dynamic_data.keys()) if 'ego_' in entity_name] + entities_errors + entities_warnings
    plot_entities = list(set(plot_entities))
    extra_plot_entities = []
    if len(plot_entities) < n_plot_entities:
        extra_plot_entities = list(set(list(dynamic_data.keys())).difference(set(plot_entities)))
        extra_plot_entities = extra_plot_entities[:n_plot_entities-len(plot_entities)]
    
    for entity_name in extra_plot_entities:
        positions, times = dynamic_data[entity_name]
        df = checker._build_dynamic_data_df(positions, times)
        df = checker._calculate_acceleration_swimangle(df)
        plot_variable(ax, df, variable, entity_name, xlabel, ylabel, save=save)
        
    ax.legend()
