# yeah!!!!!!!
# Gnuplot
import sys
import os
import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QCheckBox, QFileDialog, QSlider,
    QGridLayout, QTextEdit, QComboBox, QListWidget, QMessageBox, QDoubleSpinBox,
    QTabWidget, QGroupBox, QScrollArea, QListWidgetItem, QSizePolicy
)
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import Qt, QTimer, Signal

CREATE_NO_WINDOW = 0
if os.name == 'nt':
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW


class DropLabel(QLabel):
    fileDropped = Signal(str)

    def __init__(self, text="ここにファイルを\nドラッグ＆ドロップ"):
        super().__init__(text)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            DropLabel {
                border: 2px dashed #aaaaaa;
                border-radius: 5px;
                padding: 10px;
                background-color: #f7f7f7;
                color: #777777;
            }
            DropLabel[dragOver="true"] {
                border-color: #0078d7;
                background-color: #eaf2fa;
                color: #005a9e;
            }
        """)
        self.setProperty("dragOver", False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.setProperty("dragOver", True)
            self.style().polish(self)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragOver", False)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setProperty("dragOver", False)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if os.path.isfile(file_path):
                self.fileDropped.emit(file_path)
                event.acceptProposedAction()


class PlotItemWidget(QWidget):
    remove_clicked = Signal(QListWidgetItem)

    def __init__(self, text: str, item: QListWidgetItem):
        super().__init__()
        self.item = item

        layout = QHBoxLayout()
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(5)

        label = QLabel(text)
        label.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Preferred)

        remove_button = QPushButton("✕")
        remove_button.setFixedSize(22, 22)
        remove_button.setToolTip("このプロットを削除します")
        remove_button.clicked.connect(
            lambda: self.remove_clicked.emit(self.item))

        layout.addWidget(label)
        layout.addWidget(remove_button)
        self.setLayout(layout)


class GnuplotGUIY2Axis(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gnuplot GUI Controller (Y2-Axis Support)")
        self.setGeometry(100, 100, 1600, 950)

        self.plots = []
        self.current_selected_file_path = None
        self.dashtype_map = {"Solid": 1,
                             "Dashed": 2, "Dotted": 3, "Dash-Dot": 4}

        self.init_ui()

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.redraw_plot)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(500)

        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)

        control_layout.addWidget(self.create_plot_management_panel())
        control_layout.addWidget(self.create_general_settings_panel())
        self.style_panel = self.create_style_settings_panel()
        control_layout.addWidget(self.style_panel)
        control_layout.addWidget(self.create_axis_settings_panel())
        control_layout.addWidget(self.create_output_settings_panel())

        control_layout.addWidget(QLabel("Gnuplot Command Preview:"))
        self.script_display = QTextEdit()
        self.script_display.setReadOnly(True)
        self.script_display.setFont(QFont("Courier New", 10))
        control_layout.addWidget(self.script_display)

        control_layout.addStretch(1)

        scroll_area.setWidget(control_panel)

        self.plot_label = QLabel("Please add a plot to begin.")
        self.plot_label.setAlignment(Qt.AlignCenter)
        self.plot_label.setStyleSheet("background-color: #ffffff;")

        main_layout.addWidget(scroll_area)
        main_layout.addWidget(self.plot_label, 1)

        self.connect_signals()
        self.update_style_options_visibility()
        self.style_panel.setEnabled(False)

    def create_plot_management_panel(self):
        panel = QGroupBox("1. Plot Management")
        panel_layout = QVBoxLayout(panel)

        panel_layout.addWidget(QLabel("Current Plots:"))
        self.plot_list_widget = QListWidget()
        self.plot_list_widget.setFixedHeight(120)
        panel_layout.addWidget(self.plot_list_widget)

        add_group = QGroupBox("Add New Plot")
        add_layout = QGridLayout(add_group)

        self.drop_zone = DropLabel()
        add_layout.addWidget(self.drop_zone, 0, 0, 1, 3)

        self.new_plot_file_input = QLineEdit()
        self.new_plot_file_input.setReadOnly(True)
        self.new_plot_file_input.setPlaceholderText("ファイルを選択 or ドロップ")
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.select_plot_file)

        self.new_plot_using_input = QLineEdit("1:2")
        self.new_plot_axis_combo = QComboBox()
        self.new_plot_axis_combo.addItems(["Y1-Axis", "Y2-Axis"])

        add_plot_button = QPushButton("Add Plot")
        add_plot_button.clicked.connect(self.add_plot)

        add_layout.addWidget(QLabel("File:"), 1, 0)
        add_layout.addWidget(self.new_plot_file_input, 1, 1)
        add_layout.addWidget(browse_button, 1, 2)
        add_layout.addWidget(QLabel("Columns (using):"), 2, 0)
        add_layout.addWidget(self.new_plot_using_input, 2, 1, 1, 2)
        add_layout.addWidget(QLabel("Target Axis:"), 3, 0)
        add_layout.addWidget(self.new_plot_axis_combo, 3, 1, 1, 2)
        add_layout.addWidget(add_plot_button, 4, 0, 1, 3)

        panel_layout.addWidget(add_group)
        return panel

    def create_general_settings_panel(self):
        panel = QGroupBox("2. General Graph Settings")
        layout = QGridLayout(panel)

        ### 変更: ラベルをチェックボックスに置き換え ###
        self.title_check = QCheckBox("Graph Title:")
        self.title_check.setChecked(False)  # デフォルトはOFF
        layout.addWidget(self.title_check, 0, 0)

        self.title_input = QLineEdit("My Graph Title")
        self.title_input.setEnabled(False)  # デフォルトは無効
        layout.addWidget(self.title_input, 0, 1)

        return panel

    def create_style_settings_panel(self):
        panel = QGroupBox("3. Style Settings (for selected plot)")
        layout = QGridLayout(panel)

        layout.addWidget(QLabel("Plot Style:"), 0, 0)
        self.style_combo = QComboBox()
        self.style_combo.addItems(
            ["lines", "points", "linespoints", "dots", "impulses", "steps"])
        layout.addWidget(self.style_combo, 0, 1)
        self.color_label = QLabel("Color:")
        self.color_combo = QComboBox()
        self.color_combo.addItems(
            ["black", "red", "green", "blue", "magenta", "cyan", "yellow", "orange", "brown", "gray"])
        layout.addWidget(self.color_label, 1, 0)
        layout.addWidget(self.color_combo, 1, 1)
        self.linestyle_label = QLabel("Line Style:")
        self.linestyle_combo = QComboBox()
        self.linestyle_combo.addItems(self.dashtype_map.keys())
        layout.addWidget(self.linestyle_label, 2, 0)
        layout.addWidget(self.linestyle_combo, 2, 1)
        self.linewidth_label = QLabel("Line Width:")
        self.linewidth_spinbox = QDoubleSpinBox()
        self.linewidth_spinbox.setRange(0.1, 20.0)
        self.linewidth_spinbox.setValue(1.0)
        self.linewidth_spinbox.setSingleStep(0.1)
        layout.addWidget(self.linewidth_label, 3, 0)
        layout.addWidget(self.linewidth_spinbox, 3, 1)
        self.pointtype_label = QLabel("Point Type:")
        self.pointtype_combo = QComboBox()
        self.pointtype_combo.addItems(
            ["1: +", "2: x", "3: *", "4: □", "5: ■", "6: ○", "7: ●", "8: △", "9: ▲"])
        layout.addWidget(self.pointtype_label, 4, 0)
        layout.addWidget(self.pointtype_combo, 4, 1)
        self.pointsize_label = QLabel("Point Size:")
        self.pointsize_spinbox = QDoubleSpinBox()
        self.pointsize_spinbox.setRange(0.1, 20.0)
        self.pointsize_spinbox.setValue(1.0)
        self.pointsize_spinbox.setSingleStep(0.1)
        layout.addWidget(self.pointsize_label, 5, 0)
        layout.addWidget(self.pointsize_spinbox, 5, 1)

        return panel

    def create_axis_settings_panel(self):
        panel = QGroupBox("4. Axis Settings")
        panel_layout = QVBoxLayout(panel)
        tabs = QTabWidget()
        tabs.addTab(self.create_xaxis_tab(), "X-Axis")
        tabs.addTab(self.create_y1axis_tab(), "Y1-Axis")
        tabs.addTab(self.create_y2axis_tab(), "Y2-Axis")
        panel_layout.addWidget(tabs)
        return panel

    def create_xaxis_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("X-Axis Label:"), 0, 0)
        self.xlabel_input = QLineEdit("X-Axis")
        layout.addWidget(self.xlabel_input, 0, 1, 1, 2)
        self.xrange_check = QCheckBox("xrange")
        self.xrange_min = QLineEdit()
        self.xrange_max = QLineEdit()
        layout.addWidget(self.xrange_check, 1, 0)
        layout.addWidget(self.xrange_min, 1, 1)
        layout.addWidget(self.xrange_max, 1, 2)
        self.xtics_check = QCheckBox("xtics offset")
        self.xtics_xoffset = QLineEdit("0")
        self.xtics_yoffset = QLineEdit("-1")
        xtics_layout = QHBoxLayout()
        xtics_layout.addWidget(self.xtics_xoffset)
        xtics_layout.addWidget(QLabel(","))
        xtics_layout.addWidget(self.xtics_yoffset)
        layout.addWidget(self.xtics_check, 2, 0)
        layout.addLayout(xtics_layout, 2, 1, 1, 2)
        self.logscale_x_check = QCheckBox("Log Scale (X-Axis)")
        layout.addWidget(self.logscale_x_check, 3, 0, 1, 3)
        self.grid_check = QCheckBox("Show Grid")
        layout.addWidget(self.grid_check, 4, 0, 1, 3)
        return tab

    def create_y1axis_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("Y1-Axis Label:"), 0, 0)
        self.ylabel_input = QLineEdit("Y1-Axis")
        layout.addWidget(self.ylabel_input, 0, 1, 1, 2)
        self.yrange_check = QCheckBox("y1range")
        self.yrange_min = QLineEdit()
        self.yrange_max = QLineEdit()
        layout.addWidget(self.yrange_check, 1, 0)
        layout.addWidget(self.yrange_min, 1, 1)
        layout.addWidget(self.yrange_max, 1, 2)
        self.ytics_check = QCheckBox("y1tics offset")
        self.ytics_xoffset = QLineEdit("-1")
        self.ytics_yoffset = QLineEdit("0")
        ytics_layout = QHBoxLayout()
        ytics_layout.addWidget(self.ytics_xoffset)
        ytics_layout.addWidget(QLabel(","))
        ytics_layout.addWidget(self.ytics_yoffset)
        layout.addWidget(self.ytics_check, 2, 0)
        layout.addLayout(ytics_layout, 2, 1, 1, 2)
        self.logscale_y_check = QCheckBox("Log Scale (Y1-Axis)")
        layout.addWidget(self.logscale_y_check, 3, 0, 1, 3)
        return tab

    def create_y2axis_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("Y2-Axis Label:"), 0, 0)
        self.y2label_input = QLineEdit("Y2-Axis")
        layout.addWidget(self.y2label_input, 0, 1, 1, 2)
        self.y2range_check = QCheckBox("y2range")
        self.y2range_min = QLineEdit()
        self.y2range_max = QLineEdit()
        layout.addWidget(self.y2range_check, 1, 0)
        layout.addWidget(self.y2range_min, 1, 1)
        layout.addWidget(self.y2range_max, 1, 2)

        self.y2tics_offset_check = QCheckBox("y2tics offset")
        self.y2tics_xoffset = QLineEdit("1")
        self.y2tics_yoffset = QLineEdit("0")
        y2tics_layout = QHBoxLayout()
        y2tics_layout.addWidget(self.y2tics_xoffset)
        y2tics_layout.addWidget(QLabel(","))
        y2tics_layout.addWidget(self.y2tics_yoffset)
        layout.addWidget(self.y2tics_offset_check, 2, 0)
        layout.addLayout(y2tics_layout, 2, 1, 1, 2)

        self.logscale_y2_check = QCheckBox("Log Scale (Y2-Axis)")
        layout.addWidget(self.logscale_y2_check, 3, 0, 1, 3)
        return tab

    def create_output_settings_panel(self):
        panel = QGroupBox("5. Output Settings")
        layout = QGridLayout(panel)
        layout.addWidget(QLabel("Show Legend (key):"), 1, 0)
        self.key_check = QCheckBox()
        self.key_check.setChecked(True)
        layout.addWidget(self.key_check, 1, 1)
        self.key_pos_combo = QComboBox()
        self.key_pos_combo.addItems([
            "default", "above", "top left", "top center", "top right",
            "bottom left", "bottom center", "bottom right",
            "left center", "right center", "center",
            "outside", "below"
        ])
        layout.addWidget(self.key_pos_combo, 1, 2)
        layout.addWidget(QLabel("Image Size (W x H):"), 2, 0)
        self.width_input = QLineEdit("800")
        self.height_input = QLineEdit("600")
        size_layout = QHBoxLayout()
        size_layout.addWidget(self.width_input)
        size_layout.addWidget(QLabel("x"))
        size_layout.addWidget(self.height_input)
        layout.addLayout(size_layout, 2, 1, 1, 2)
        layout.addWidget(QLabel("Font:"), 3, 0)
        self.font_combo = QComboBox()
        self.font_combo.addItems(
            ["Times New Roman", "Arial", "Helvetica", "Verdana", "Courier New"])
        layout.addWidget(self.font_combo, 3, 1, 1, 2)
        layout.addWidget(QLabel("Font Size:"), 4, 0)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 30)
        self.font_slider.setValue(14)
        self.font_label = QLabel("14")
        font_layout = QHBoxLayout()
        font_layout.addWidget(self.font_slider)
        font_layout.addWidget(self.font_label)
        layout.addLayout(font_layout, 4, 1, 1, 2)
        self.save_button = QPushButton("Save Graph As...")
        self.save_button.clicked.connect(self.save_image)
        layout.addWidget(self.save_button, 5, 0, 1, 3)
        return panel

    def connect_signals(self):
        self.drop_zone.fileDropped.connect(self.handle_dropped_file)

        ### 追加: タイトルチェックボックスのシグナルを接続 ###
        self.title_check.stateChanged.connect(self.update_title_input_state)
        # 再描画もトリガーするように接続を追加
        self.title_check.stateChanged.connect(self.request_redraw)

        # タイトル入力欄のtextChangedは常に再描画をリクエストしてOK
        self.title_input.textChanged.connect(self.request_redraw)

        for widget in [self.xlabel_input, self.ylabel_input, self.y2label_input,
                       self.xrange_min, self.xrange_max, self.yrange_min, self.yrange_max, self.y2range_min, self.y2range_max,
                       self.xtics_xoffset, self.xtics_yoffset, self.ytics_xoffset, self.ytics_yoffset,
                       self.y2tics_xoffset, self.y2tics_yoffset,
                       self.width_input, self.height_input, self.key_pos_combo, self.font_combo]:
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.request_redraw)
            else:
                widget.currentIndexChanged.connect(self.request_redraw)

        for widget in [self.xrange_check, self.yrange_check, self.y2range_check, self.xtics_check, self.ytics_check,
                       self.y2tics_offset_check,
                       self.logscale_x_check, self.logscale_y_check, self.logscale_y2_check, self.grid_check, self.key_check]:
            widget.stateChanged.connect(self.request_redraw)

        self.font_slider.valueChanged.connect(
            lambda v: self.font_label.setText(str(v)))
        self.font_slider.valueChanged.connect(self.request_redraw)

        self.plot_list_widget.currentItemChanged.connect(
            self.on_plot_selection_changed)
        self.style_combo.currentIndexChanged.connect(
            self.update_selected_plot_style)
        self.style_combo.currentIndexChanged.connect(
            self.update_style_options_visibility)
        for widget in [self.color_combo, self.linestyle_combo, self.pointtype_combo]:
            widget.currentIndexChanged.connect(self.update_selected_plot_style)
        for widget in [self.linewidth_spinbox, self.pointsize_spinbox]:
            widget.valueChanged.connect(self.update_selected_plot_style)

    ### 追加: タイトル入力欄の有効/無効を切り替えるスロット ###
    def update_title_input_state(self):
        self.title_input.setEnabled(self.title_check.isChecked())

    def handle_dropped_file(self, file_path):
        if os.path.isfile(file_path):
            self.current_selected_file_path = file_path
            self.new_plot_file_input.setText(os.path.basename(file_path))

    def request_redraw(self):
        self.update_timer.start(500)

    def update_style_options_visibility(self):
        style = self.style_combo.currentText()
        is_line_style = "lines" in style or style == "steps"
        is_point_style = "points" in style

        self.linestyle_label.setVisible(is_line_style)
        self.linestyle_combo.setVisible(is_line_style)
        self.linewidth_label.setVisible(is_line_style)
        self.linewidth_spinbox.setVisible(is_line_style)
        self.pointtype_label.setVisible(is_point_style)
        self.pointtype_combo.setVisible(is_point_style)
        self.pointsize_label.setVisible(is_point_style)
        self.pointsize_spinbox.setVisible(is_point_style)
        self.color_label.setVisible(is_line_style or is_point_style)
        self.color_combo.setVisible(is_line_style or is_point_style)

    def select_plot_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Data File", "", "Data Files (*.dat *.txt);;All Files (*)")
        if file_name:
            self.current_selected_file_path = file_name
            self.new_plot_file_input.setText(os.path.basename(file_name))

    def add_plot(self):
        if not self.current_selected_file_path:
            QMessageBox.warning(self, "Warning", "Please select a file first.")
            return

        using = self.new_plot_using_input.text().strip()
        if not using:
            QMessageBox.warning(
                self, "Warning", "Please specify the columns to use (e.g., 1:2).")
            return

        axis = "y1" if self.new_plot_axis_combo.currentIndex() == 0 else "y2"

        default_style = {"style": self.style_combo.currentText(), "color": self.color_combo.currentText(), "linestyle": self.linestyle_combo.currentText(
        ), "linewidth": self.linewidth_spinbox.value(), "pointtype": self.pointtype_combo.currentIndex() + 1, "pointsize": self.pointsize_spinbox.value()}

        plot_info = {"path": self.current_selected_file_path, "using": using, "axis": axis,
                     "title": f"{os.path.basename(self.current_selected_file_path)} u {using} ({axis})", "style": default_style}
        self.plots.append(plot_info)

        list_item = QListWidgetItem(self.plot_list_widget)
        item_widget = PlotItemWidget(plot_info["title"], list_item)
        item_widget.remove_clicked.connect(self.handle_remove_request)

        list_item.setSizeHint(item_widget.sizeHint())
        self.plot_list_widget.setItemWidget(list_item, item_widget)

        self.plot_list_widget.setCurrentItem(list_item)
        self.new_plot_file_input.clear()
        self.current_selected_file_path = None
        self.request_redraw()

    def handle_remove_request(self, item):
        row = self.plot_list_widget.row(item)
        if row >= 0:
            self.plot_list_widget.takeItem(row)
            self.plots.pop(row)
            self.request_redraw()

    def on_plot_selection_changed(self, current, previous):
        if not current:
            self.style_panel.setEnabled(False)
            return

        self.style_panel.setEnabled(True)
        row = self.plot_list_widget.row(current)
        if row >= 0:
            plot_style = self.plots[row]["style"]

            self.style_combo.blockSignals(True)
            self.style_combo.setCurrentText(plot_style["style"])
            self.style_combo.blockSignals(False)
            self.color_combo.blockSignals(True)
            self.color_combo.setCurrentText(plot_style["color"])
            self.color_combo.blockSignals(False)
            self.linestyle_combo.blockSignals(True)
            self.linestyle_combo.setCurrentText(plot_style["linestyle"])
            self.linestyle_combo.blockSignals(False)
            self.pointtype_combo.blockSignals(True)
            self.pointtype_combo.setCurrentIndex(plot_style["pointtype"] - 1)
            self.pointtype_combo.blockSignals(False)
            self.linewidth_spinbox.blockSignals(True)
            self.linewidth_spinbox.setValue(plot_style["linewidth"])
            self.linewidth_spinbox.blockSignals(False)
            self.pointsize_spinbox.blockSignals(True)
            self.pointsize_spinbox.setValue(plot_style["pointsize"])
            self.pointsize_spinbox.blockSignals(False)

            self.update_style_options_visibility()

    def update_selected_plot_style(self):
        if not self.plot_list_widget.currentItem():
            return

        row = self.plot_list_widget.currentRow()
        if row >= 0:
            self.plots[row]["style"]["style"] = self.style_combo.currentText()
            self.plots[row]["style"]["color"] = self.color_combo.currentText()
            self.plots[row]["style"]["linestyle"] = self.linestyle_combo.currentText()
            self.plots[row]["style"]["linewidth"] = self.linewidth_spinbox.value()
            self.plots[row]["style"]["pointtype"] = self.pointtype_combo.currentIndex(
            ) + 1
            self.plots[row]["style"]["pointsize"] = self.pointsize_spinbox.value()

            self.request_redraw()

    def generate_gnuplot_script(self, output_path=None, terminal_cmd=None):
        if not self.plots:
            return None

        if terminal_cmd:
            script = f"{terminal_cmd}\n"
        else:
            font_setting = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
            width = int(self.width_input.text() or "800")
            height = int(self.height_input.text() or "600")
            script = f'set terminal pngcairo size {width},{height} enhanced {font_setting}\n'

        if output_path:
            script += f'set output "{output_path}"\n'

        script += 'set encoding utf8\n'

        ### 変更: チェックボックスの状態を見てtitleコマンドを生成 ###
        if self.title_check.isChecked() and self.title_input.text():
            script += f'set title "{self.title_input.text()}"\n'

        if self.xlabel_input.text():
            script += f'set xlabel "{self.xlabel_input.text()}"\n'
        if self.ylabel_input.text():
            script += f'set ylabel "{self.ylabel_input.text()}"\n'

        has_y2 = any(p['axis'] == 'y2' for p in self.plots)
        if has_y2 and self.y2label_input.text():
            script += f'set y2label "{self.y2label_input.text()}"\n'

        if self.xrange_check.isChecked() and self.xrange_min.text() and self.xrange_max.text():
            script += f'set xrange [{self.xrange_min.text()}:{self.xrange_max.text()}]\n'
        if self.yrange_check.isChecked() and self.yrange_min.text() and self.yrange_max.text():
            script += f'set yrange [{self.yrange_min.text()}:{self.yrange_max.text()}]\n'
        if has_y2 and self.y2range_check.isChecked() and self.y2range_min.text() and self.y2range_max.text():
            script += f'set y2range [{self.y2range_min.text()}:{self.y2range_max.text()}]\n'

        if self.xtics_check.isChecked():
            script += f'set xtics offset {self.xtics_xoffset.text() or "0"},{self.xtics_yoffset.text() or "0"}\n'
        if self.ytics_check.isChecked():
            script += f'set ytics offset {self.ytics_xoffset.text() or "0"},{self.ytics_yoffset.text() or "0"}\n'

        if has_y2:
            script += 'set ytics nomirror\n'
            script += 'set y2tics\n'
            if self.y2tics_offset_check.isChecked():
                script += f'set y2tics offset {self.y2tics_xoffset.text() or "0"},{self.y2tics_yoffset.text() or "0"}\n'

        log_axes = ""
        if self.logscale_x_check.isChecked():
            log_axes += "x"
        if self.logscale_y_check.isChecked():
            log_axes += "y"
        if has_y2 and self.logscale_y2_check.isChecked():
            log_axes += "y2"
        if log_axes:
            script += f'set logscale {log_axes}\n'
        else:
            script += 'unset logscale\n'

        if self.grid_check.isChecked():
            script += 'set grid\n'
        if self.key_check.isChecked():
            script += f'set key {self.key_pos_combo.currentText()}\n'
        else:
            script += 'set key off\n'

        plot_parts = []
        for plot_info in self.plots:
            style_info = plot_info["style"]
            style = style_info["style"]
            is_line = "lines" in style or style == "steps"
            is_point = "points" in style

            style_details = f"with {style}"
            if is_line:
                dt_key = style_info['linestyle']
                dt_val = self.dashtype_map.get(dt_key, 1)
                style_details += f" dashtype {dt_val} linewidth {style_info['linewidth']}"
            if is_point:
                style_details += f" pointtype {style_info['pointtype']} pointsize {style_info['pointsize']}"
            if is_line or is_point:
                style_details += f' linecolor rgb "{style_info["color"]}"'

            axis_cmd = "x1y1" if plot_info["axis"] == "y1" else "x1y2"
            plot_parts.append(
                f'"{plot_info["path"]}" using {plot_info["using"]} axes {axis_cmd} {style_details} title "{plot_info["title"]}"')

        if plot_parts:
            script += "plot " + ", \\\n  ".join(plot_parts) + "\n"

        return script

    def redraw_plot(self):
        script = self.generate_gnuplot_script()

        if not script:
            self.plot_label.setText("Please add a plot to begin.")
            self.script_display.clear()
            self.script_display.setFixedHeight(30)
            return

        self.script_display.setText(script)

        content_height = self.script_display.document().size().height()
        new_height = int(content_height) + 10
        self.script_display.setFixedHeight(new_height)

        try:
            process = subprocess.Popen(['gnuplot'],
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       creationflags=CREATE_NO_WINDOW)

            stdout_data, stderr_data = process.communicate(
                script.encode('utf-8'))

            if process.returncode != 0:
                self.plot_label.setText(
                    f"Gnuplot Error:\n{stderr_data.decode('utf-8', 'ignore')}")
                return

            pixmap = QPixmap()
            if pixmap.loadFromData(stdout_data):
                self.plot_label.setPixmap(pixmap.scaled(
                    self.plot_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.plot_label.setText("Failed to load image from Gnuplot.")

        except Exception as e:
            self.plot_label.setText(f"Runtime Error:\n{e}")

    def save_image(self):
        if not self.plots:
            QMessageBox.warning(self, "Error", "No data to plot.")
            return
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self, "Save Graph As", "", "PNG Image (*.png);;SVG Image (*.svg);;PDF Document (*.pdf);;All Files (*)")
        if not file_name:
            return

        width = int(self.width_input.text() or "800")
        height = int(self.height_input.text() or "900")
        font_setting = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'

        if "svg" in selected_filter:
            term_cmd = f'set terminal svg size {width},{height} {font_setting}'
        elif "pdf" in selected_filter:
            term_cmd = f'set terminal pdfcairo size {width/100.0},{height/100.0} {font_setting}'
        else:
            term_cmd = f'set terminal pngcairo size {width},{height} enhanced {font_setting}'

        script = self.generate_gnuplot_script(
            output_path=file_name, terminal_cmd=term_cmd)

        if not script:
            QMessageBox.critical(self, "Error", "Failed to generate script.")
            return
        try:
            process = subprocess.Popen(['gnuplot'],
                                       stdin=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       text=True,
                                       encoding='utf-8',
                                       creationflags=CREATE_NO_WINDOW)
            _, stderr = process.communicate(script)
            if process.returncode == 0:
                QMessageBox.information(
                    self, "Success", f"Graph saved to {file_name}")
            else:
                QMessageBox.critical(self, "Gnuplot Error",
                                     f"Failed to save graph.\n\n{stderr}")
        except Exception as e:
            QMessageBox.critical(self, "Runtime Error",
                                 f"An error occurred.\n\n{e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.plot_list_widget.count() > 0 or len(self.plots) > 0:
            self.request_redraw()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = GnuplotGUIY2Axis()
    window.show()
    sys.exit(app.exec())
