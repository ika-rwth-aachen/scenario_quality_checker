"""
template for pdf file creation
"""

from fpdf import FPDF
import ctypes


class PDF(FPDF):
    """
    creating a pdf file
    """
    def __init__(self, header_text=None, footer_text=None, font_type="Arial", font_size=15, color=(0, 0, 0)):
        """
        initialise layout of pdf
        Args:
            header_text: header of pdf
            footer_text: footer of pdf
            font_type: name of font
            font_size: size of font
        """
        FPDF.__init__(self)
        self.header_text = header_text
        self.footer_text = footer_text
        self.defaut_font = {"size": font_size, "name": font_type, "type": ""}
        self.set_font(font_type, '', font_size)
        self.set_text_color(color)
        self.set_left_margin(20)

    def header(self):
        """
        creating header if header is set
        """
        if self.header_text:
            # Arial bold 15
            self.set_font(self.defaut_font["name"], 'B', 15)
            # Title
            self.cell(170, 10, self.header_text, 0, 0, 'C')
            # Line break
            self.ln(20)

    def footer(self):
        """
        footline
        """
        # Position at 1.5 cm from bottom
        self.set_y(-15)
        self.set_x(-20)
        # Arial italic 8
        self.set_font(self.defaut_font["name"], 'I', 9)
        self.set_text_color((0, 0, 0))
        # Page number
        self.cell(0, 10, 'Page ' + str(self.page_no()) + '/{nb}', 0, 0, 'R')

        # default footer text
        if self.footer_text:
            self.set_x(-105)
            self.cell(40, 10, self.footer_text, 0, 0, "C")

    def create_textbox(self, text, font=None, color=(0, 0, 0), set_box=False, relative_position=None, absolute_position=None):
        """
        create text box
        Args:
            text: text to write
            font: font if other is wanted
            set_box: black line around text if wanted
            relative_position: offset from actual position
            absolute_position: absolute possition of text box
        """
        if not font:
            font = self.defaut_font
        self.set_font(font["name"], font["type"], font["size"])
        self.set_text_color(color)

        boarder = 1 if set_box else 0
        text_length, text_height = self._get_text_dimensions(text, font["name"], font["size"])

        if relative_position:
            self._set_relative_offset(relative_position[0], relative_position[1])
        else:
            if absolute_position:
                self.set_x(absolute_position[0])
                self.set_y(absolute_position[1])
        self.cell(text_length, text_height, text, boarder, 0, "L")

        self.ln(text_height)

    def create_image(self, image_path, size, relative_position=None, absolute_position=None):
        """
        sets an image in pdf
        Args:
            image_path: path of image
            size: size of the image in mm
            relative_position: offset from actual position
            absolute_position: absolute position on page - only used if relative_position not set
        """
        x_position, y_position = 0, 0
        if relative_position:
            x_position = self.get_x() + relative_position[0]
            y_position = self.get_y() + relative_position[1]
        else:
            if absolute_position:
                x_position = absolute_position[0]
                y_position = absolute_position[1]
        self.image(image_path, w=size[0], h=size[1], x=x_position, y=y_position)

    def create_table(self, data, columns=None, relative_position=None, absolute_position=None, font=None,
                     font_size=None, title=None, title_font=None, size_rows=None, size_columns=None, show_lines=True,
                     cell_position=None):
        """
        creating a table in pdf
        Args:
            columns: column titles of table
            data: actual table data
            relative_position: position of upper left corner relativly to actual position
            absolute_position: absolute position of left up corner on page
            font: font style (if different)
            font_size: font size (if different)
            title: header of table
            title_font: header style
            size_rows: set custom length of cells in mm
            size_columns: set custom height of cells in mm
            show_lines: weather to show bounding boxes
            cell_position: array of l, c, r for position in each column
        """
        # set font
        if not font:
            font = self.defaut_font["name"]
        if not font_size:
            font_size = self.defaut_font["size"]
        self.set_font(font, '', font_size)
        if not title_font:
            title_font = {"style": font, "size": font_size+3}
        if show_lines:
            show_lines = 1
        else:
            show_lines = 0
        if not cell_position:
            cell_position = ["C"] * len(data[0])

        # put information in one list
        information = []
        if columns:
            information.append(columns)
        information.extend(data)

        # set offset for initial offset
        if relative_position:
            self._set_relative_offset(relative_position[0], relative_position[1])
            x_offset = relative_position[0]
        else:
            if absolute_position:
                self.set_x(absolute_position[0])
                self.set_y(absolute_position[1])
                x_offset = absolute_position[0]
            else:
                x_offset = 0

        # get minimal table
        if (not size_columns) or (not size_rows):
            check_for_rows = False
            check_for_columns = False
            if not size_rows:
                size_rows = [0] * len(information)
                check_for_rows = True
            if not size_columns:
                size_columns = [0] * len(information[0])
                check_for_columns = True
            for index_column, column in enumerate(information[0]):
                for index_row, row in enumerate(information):
                    cell = information[index_row][index_column]
                    length, height = self._get_text_dimensions(str(cell), font, font_size)
                    if check_for_rows:
                        size_rows[index_row] = max(size_rows[index_row], height)
                    if check_for_columns:
                        size_columns[index_column] = max(size_columns[index_column], length)

        # plot header
        if title:
            title_dimensions = self._get_text_dimensions(title, title_font["style"], title_font["size"])
            self.cell(max(0.01, x_offset), title_dimensions[1], "", 0, 0, "C")
            self.set_font(title_font["style"], "B", title_font["size"])
            self.cell(title_dimensions[0], title_dimensions[1], title, 0, 0, "L")
            self.ln(title_dimensions[1])

        # plot table
        for index_row, row in enumerate(information):
            self.cell(max(x_offset, 0.01), 0.1, "", 0, 0, "C")
            for index_column, column in enumerate(information[0]):
                if index_row == 0 and columns:
                    self.set_font(font, 'B', font_size)
                    self.cell(size_columns[index_column], size_rows[index_row], str(information[index_row][index_column]), show_lines, 0, cell_position[index_column])
                else:
                    self.set_font(font, '', font_size)
                    self.cell(size_columns[index_column], size_rows[index_row], str(information[index_row][index_column]), show_lines, 0, cell_position[index_column])
            self.ln(size_rows[index_row])
            
    def create_line(self, color=(0, 0, 0), relative_position=None, absolute_position=None):
        x_position, y_position = 0, 0
        if relative_position:
            x_position = self.get_x() + relative_position[0]
            y_position = self.get_y() + relative_position[1]
        else:
            if absolute_position:
                x_position = absolute_position[0]
                y_position = absolute_position[1]
                
        self.line(x_position, y_position, x_position+170, y_position)
            
    def _set_relative_offset(self, offset_x, offset_y):
        """
        create an offset from last cell
        Args:
            offset_x: offset in x direction in mm
            offset_y: offset in y direction in mm
        """
        self.set_x(self.get_x() + offset_x)
        self.set_y(self.get_y() + offset_y)

    @staticmethod
    def _get_text_dimensions(text, font, font_size):
        """
        get length and width of text
        Args:
            text: given text
            font: style
            font_size: size of style
        return: length and height of text
        """
        try:
            # accurate calculation for windows
            class SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            hdc = ctypes.windll.user32.GetDC(0)
            hfont = ctypes.windll.gdi32.CreateFontA(font_size, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, font)
            hfont_old = ctypes.windll.gdi32.SelectObject(hdc, hfont)

            size = SIZE(0, 0)
            ctypes.windll.gdi32.GetTextExtentPoint32A(hdc, text, len(text), ctypes.byref(size))

            ctypes.windll.gdi32.SelectObject(hdc, hfont_old)
            ctypes.windll.gdi32.DeleteObject(hfont)

            return size.cx, size.cy
        except AttributeError:
            # less accurate for other enviroments
            return font_size * len(text) * 0.5, font_size
