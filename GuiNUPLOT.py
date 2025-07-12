import sys
import os
import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QCheckBox, QFileDialog, QSlider,
    QGridLayout, QTextEdit, QComboBox, QMessageBox, QDoubleSpinBox,
    QTabWidget, QGroupBox, QScrollArea, QSizePolicy, QMenu
)
from PySide6.QtGui import QFont, QPixmap, QAction
from PySide6.QtCore import Qt, QTimer, Signal
import functools

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

# 各プロットの編集UIを含むカスタムウィジェット
class PlotEditorWidget(QWidget):
    def __init__(self, plot_info, dashtype_map, parent=None):
        super().__init__(parent)
        self.plot_info = plot_info
        self.dashtype_map = dashtype_map
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5) # 余白を調整

        # プロット詳細セクション
        details_group = QGroupBox("Plot Details")
        details_layout = QGridLayout(details_group)

        details_layout.addWidget(QLabel("File Path:"), 0, 0)
        self.file_path_input = QLineEdit(self.plot_info["file_path"])
        self.file_path_input.setReadOnly(True)
        details_layout.addWidget(self.file_path_input, 0, 1)
        self.browse_button = QPushButton("Browse...")
        details_layout.addWidget(self.browse_button, 0, 2)

        details_layout.addWidget(QLabel("Columns (using):"), 1, 0)
        self.using_input = QLineEdit(self.plot_info["using"])
        details_layout.addWidget(self.using_input, 1, 1, 1, 2)

        details_layout.addWidget(QLabel("Target Axis:"), 2, 0)
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["Y1-Axis", "Y2-Axis"])
        self.axis_combo.setCurrentIndex(0 if self.plot_info["axis"] == "y1" else 1)
        details_layout.addWidget(self.axis_combo, 2, 1, 1, 2)

        details_layout.addWidget(QLabel("Plot Title (Legend):"), 3, 0)
        self.title_input = QLineEdit(self.plot_info["title"])
        details_layout.addWidget(self.title_input, 3, 1, 1, 2)
        
        layout.addWidget(details_group)

        # スタイル設定セクション
        style_group = QGroupBox("Style Settings")
        style_layout = QGridLayout(style_group)

        style_layout.addWidget(QLabel("Plot Style:"), 0, 0)
        self.style_combo = QComboBox()
        self.style_combo.addItems(["lines", "points", "linespoints", "dots", "impulses", "steps"])
        self.style_combo.setCurrentText(self.plot_info["style"]["style"])
        style_layout.addWidget(self.style_combo, 0, 1)

        self.color_label = QLabel("Color:")
        self.color_combo = QComboBox()
        self.color_combo.addItems(["black", "red", "green", "blue", "magenta", "cyan", "yellow", "orange", "brown", "gray"])
        self.color_combo.setCurrentText(self.plot_info["style"]["color"])
        style_layout.addWidget(self.color_label, 1, 0)
        style_layout.addWidget(self.color_combo, 1, 1)

        self.linestyle_label = QLabel("Line Style:")
        self.linestyle_combo = QComboBox()
        self.linestyle_combo.addItems(self.dashtype_map.keys())
        self.linestyle_combo.setCurrentText(self.plot_info["style"]["linestyle"])
        style_layout.addWidget(self.linestyle_label, 2, 0)
        style_layout.addWidget(self.linestyle_combo, 2, 1)

        self.linewidth_label = QLabel("Line Width:")
        self.linewidth_spinbox = QDoubleSpinBox()
        self.linewidth_spinbox.setRange(0.1, 20.0)
        self.linewidth_spinbox.setValue(self.plot_info["style"]["linewidth"])
        self.linewidth_spinbox.setSingleStep(0.1)
        style_layout.addWidget(self.linewidth_label, 3, 0)
        style_layout.addWidget(self.linewidth_spinbox, 3, 1)

        self.pointtype_label = QLabel("Point Type:")
        self.pointtype_combo = QComboBox()
        self.pointtype_combo.addItems(["1: +", "2: x", "3: *", "4: □", "5: ■", "6: ○", "7: ●", "8: △", "9: ▲"])
        self.pointtype_combo.setCurrentIndex(self.plot_info["style"]["pointtype"] - 1)
        style_layout.addWidget(self.pointtype_label, 4, 0)
        style_layout.addWidget(self.pointtype_combo, 4, 1)

        self.pointsize_label = QLabel("Point Size:")
        self.pointsize_spinbox = QDoubleSpinBox()
        self.pointsize_spinbox.setRange(0.1, 20.0)
        self.pointsize_spinbox.setValue(self.plot_info["style"]["pointsize"])
        self.pointsize_spinbox.setSingleStep(0.1)
        style_layout.addWidget(self.pointsize_label, 5, 0)
        style_layout.addWidget(self.pointsize_spinbox, 5, 1)
        
        layout.addWidget(style_group)
        layout.addStretch(1) # 下にスペースを詰める

        self.update_style_options_visibility() # 初期表示時のスタイルオプション可視性設定
        self.connect_signals()

    def connect_signals(self):
        self.browse_button.clicked.connect(self.select_file_for_plot)

        self.using_input.textChanged.connect(self._update_plot_info)
        self.axis_combo.currentIndexChanged.connect(self._update_plot_info)
        self.title_input.textChanged.connect(self._update_plot_info)

        self.style_combo.currentIndexChanged.connect(self._update_plot_info)
        self.style_combo.currentIndexChanged.connect(self.update_style_options_visibility) # スタイル変更時にオプションの可視性を更新
        self.color_combo.currentIndexChanged.connect(self._update_plot_info)
        self.linestyle_combo.currentIndexChanged.connect(self._update_plot_info)
        self.linewidth_spinbox.valueChanged.connect(self._update_plot_info)
        self.pointtype_combo.currentIndexChanged.connect(self._update_plot_info)
        self.pointsize_spinbox.valueChanged.connect(self._update_plot_info)

    def _update_plot_info(self):
        """UI要素の変更をplot_infoに反映し、メインウィンドウに再描画をリクエストする"""
        # シグナルを一時的にブロックして、再帰呼び出しを防ぐ（特にtitle_inputと_update_tab_title_and_redrawの連携時）
        self.blockSignals(True) 

        self.plot_info["using"] = self.using_input.text()
        self.plot_info["axis"] = "y1" if self.axis_combo.currentIndex() == 0 else "y2"
        self.plot_info["title"] = self.title_input.text()

        self.plot_info["style"]["style"] = self.style_combo.currentText()
        self.plot_info["style"]["color"] = self.color_combo.currentText()
        self.plot_info["style"]["linestyle"] = self.linestyle_combo.currentText()
        self.plot_info["style"]["linewidth"] = self.linewidth_spinbox.value()
        self.plot_info["style"]["pointtype"] = self.pointtype_combo.currentIndex() + 1
        self.plot_info["style"]["pointsize"] = self.pointsize_spinbox.value()

        # メインウィンドウに通知して再描画をリクエスト
        # PlotEditorWidgetの親がQTabWidgetであることを前提とする
        parent_tab_widget = self.parent() 
        if isinstance(parent_tab_widget, QTabWidget):
            main_window = parent_tab_widget.parent().parent() # QTabWidget -> QGroupBox -> QVBoxLayout -> QMainWindow
            if isinstance(main_window, GnuplotGUIY2Axis):
                # 凡例タイトルが変わったらタブのタイトルも更新
                tab_index = main_window.plot_tabs.indexOf(self)
                if tab_index != -1:
                    main_window.plot_tabs.setTabText(tab_index, self.plot_info["title"])
                main_window.request_redraw()
        
        self.blockSignals(False)

    def select_file_for_plot(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Data File for Plot", "", "Data Files (*.dat *.txt);;All Files (*)")
        if file_name:
            self.file_path_input.setText(file_name)
            self.plot_info["file_path"] = file_name
            self._update_plot_info() # 変更を反映して再描画

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


class GnuplotGUIY2Axis(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gnuplot GUI Controller (Y2-Axis Support)")
        self.setGeometry(100, 100, 1600, 950)

        self.plots = [] # 実際に描画するプロット情報のリスト
        self.available_files = [] # 登録されたファイルのパスのリスト (重複なし)

        self.dashtype_map = {"Solid": 1, "Dashed": 2, "Dotted": 3, "Dash-Dot": 4}

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
        scroll_area.setFixedWidth(500) # コントロールパネルの幅

        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        
        control_layout.addWidget(self.create_plot_management_panel())
        control_layout.addWidget(self.create_general_settings_panel())
        # Style Settings パネルは PlotEditorWidget に統合されたため、ここでは作成しない
        self.style_panel = QGroupBox("3. Style Settings (Moved to Plot Tab)") # ダミーとして残す
        self.style_panel.setEnabled(False) # 常に無効
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
        # update_style_options_visibility は PlotEditorWidget 内で呼び出される
        self.update_add_plot_controls_state() # 追加ボタンの初期状態設定

    def create_plot_management_panel(self):
        panel = QGroupBox("1. Plot Management")
        panel_layout = QVBoxLayout(panel)

        # ファイル登録セクション (ドロップゾーンとファイル選択ボタンのみ)
        register_file_group = QGroupBox("Register Data File")
        register_layout = QGridLayout(register_file_group)
        self.drop_zone = DropLabel()
        register_layout.addWidget(self.drop_zone, 0, 0, 1, 3)
        register_file_browse_button = QPushButton("Browse Files...")
        register_file_browse_button.setObjectName("registerFileBrowseButton") # ここにオブジェクト名を設定
        
        register_layout.addWidget(register_file_browse_button, 1, 0, 1, 3)
        panel_layout.addWidget(register_file_group)

        # 利用可能なファイルリスト (QComboBox に変更)
        panel_layout.addWidget(QLabel("Select Registered File:"))
        self.available_files_combo = QComboBox()
        self.available_files_combo.setPlaceholderText("ファイルを選択")
        panel_layout.addWidget(self.available_files_combo)

        # プロット追加設定セクション
        add_plot_group = QGroupBox("Add Plot from Selected File")
        add_layout = QGridLayout(add_plot_group)
        
        self.new_plot_using_input = QLineEdit("1:2")
        self.new_plot_axis_combo = QComboBox()
        self.new_plot_axis_combo.addItems(["Y1-Axis", "Y2-Axis"])
        self.new_plot_title_input = QLineEdit() 
        self.new_plot_title_input.setPlaceholderText("凡例タイトル (オプション)")
        
        self.add_plot_button = QPushButton("Add Plot")
        
        add_layout.addWidget(QLabel("Columns (using):"), 0, 0); add_layout.addWidget(self.new_plot_using_input, 0, 1, 1, 2)
        add_layout.addWidget(QLabel("Target Axis:"), 1, 0); add_layout.addWidget(self.new_plot_axis_combo, 1, 1, 1, 2)
        add_layout.addWidget(QLabel("Plot Title:"), 2, 0); add_layout.addWidget(self.new_plot_title_input, 2, 1, 1, 2)
        add_layout.addWidget(self.add_plot_button, 3, 0, 1, 3)
        panel_layout.addWidget(add_plot_group)

        # 現在のプロットリスト (QTabWidget に変更)
        panel_layout.addWidget(QLabel("Current Plots (Click tab to edit, X to remove):"))
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setTabsClosable(True) # タブに閉じるボタンを追加
        self.plot_tabs.setFixedHeight(300) # タブウィジェットの高さ固定
        panel_layout.addWidget(self.plot_tabs)
        
        return panel

    def create_general_settings_panel(self):
        panel = QGroupBox("2. General Graph Settings")
        layout = QGridLayout(panel)
        
        self.title_check = QCheckBox("Graph Title:")
        self.title_check.setChecked(False) 
        layout.addWidget(self.title_check, 0, 0)
        
        self.title_input = QLineEdit("My Graph Title")
        self.title_input.setEnabled(False) 
        layout.addWidget(self.title_input, 0, 1)

        return panel

    def create_axis_settings_panel(self):
        panel = QGroupBox("4. Axis Settings")
        panel_layout = QVBoxLayout(panel)
        tabs = QTabWidget()
        tabs.addTab(self.create_xaxis_tab(), "X-Axis"); tabs.addTab(self.create_y1axis_tab(), "Y1-Axis"); tabs.addTab(self.create_y2axis_tab(), "Y2-Axis")
        panel_layout.addWidget(tabs)
        return panel

    def create_xaxis_tab(self):
        tab = QWidget(); layout = QGridLayout(tab)
        layout.addWidget(QLabel("X-Axis Label:"), 0, 0); self.xlabel_input = QLineEdit("X-Axis"); layout.addWidget(self.xlabel_input, 0, 1, 1, 2)
        self.xrange_check = QCheckBox("xrange"); self.xrange_min = QLineEdit(); self.xrange_max = QLineEdit(); layout.addWidget(self.xrange_check, 1, 0); layout.addWidget(self.xrange_min, 1, 1); layout.addWidget(self.xrange_max, 1, 2)
        self.xtics_check = QCheckBox("xtics offset"); self.xtics_xoffset = QLineEdit("0"); self.xtics_yoffset = QLineEdit("-1"); xtics_layout = QHBoxLayout(); xtics_layout.addWidget(self.xtics_xoffset); xtics_layout.addWidget(QLabel(",")); xtics_layout.addWidget(self.xtics_yoffset); layout.addWidget(self.xtics_check, 2, 0); layout.addLayout(xtics_layout, 2, 1, 1, 2)
        self.logscale_x_check = QCheckBox("Log Scale (X-Axis)"); layout.addWidget(self.logscale_x_check, 3, 0, 1, 3)
        self.grid_check = QCheckBox("Show Grid"); layout.addWidget(self.grid_check, 4, 0, 1, 3)
        return tab

    def create_y1axis_tab(self):
        tab = QWidget(); layout = QGridLayout(tab)
        layout.addWidget(QLabel("Y1-Axis Label:"), 0, 0); self.ylabel_input = QLineEdit("Y1-Axis"); layout.addWidget(self.ylabel_input, 0, 1, 1, 2)
        self.yrange_check = QCheckBox("y1range"); self.yrange_min = QLineEdit(); self.yrange_max = QLineEdit(); layout.addWidget(self.yrange_check, 1, 0); layout.addWidget(self.yrange_min, 1, 1); layout.addWidget(self.yrange_max, 1, 2)
        self.ytics_check = QCheckBox("y1tics offset"); self.ytics_xoffset = QLineEdit("-1"); self.ytics_yoffset = QLineEdit("0"); ytics_layout = QHBoxLayout(); ytics_layout.addWidget(self.ytics_xoffset); ytics_layout.addWidget(QLabel(",")); ytics_layout.addWidget(self.ytics_yoffset); layout.addWidget(self.ytics_check, 2, 0); layout.addLayout(ytics_layout, 2, 1, 1, 2)
        self.logscale_y_check = QCheckBox("Log Scale (Y1-Axis)"); layout.addWidget(self.logscale_y_check, 3, 0, 1, 3)
        return tab

    def create_y2axis_tab(self):
        tab = QWidget(); layout = QGridLayout(tab)
        layout.addWidget(QLabel("Y2-Axis Label:"), 0, 0); self.y2label_input = QLineEdit("Y2-Axis"); layout.addWidget(self.y2label_input, 0, 1, 1, 2)
        self.y2range_check = QCheckBox("y2range"); self.y2range_min = QLineEdit(); self.y2range_max = QLineEdit(); layout.addWidget(self.y2range_check, 1, 0); layout.addWidget(self.y2range_min, 1, 1); layout.addWidget(self.y2range_max, 1, 2)
        
        self.y2tics_offset_check = QCheckBox("y2tics offset")
        self.y2tics_xoffset = QLineEdit("1")
        self.y2tics_yoffset = QLineEdit("0")
        y2tics_layout = QHBoxLayout()
        y2tics_layout.addWidget(self.y2tics_xoffset)
        y2tics_layout.addWidget(QLabel(","))
        y2tics_layout.addWidget(self.y2tics_yoffset)
        layout.addWidget(self.y2tics_offset_check, 2, 0)
        layout.addLayout(y2tics_layout, 2, 1, 1, 2)
        
        self.logscale_y2_check = QCheckBox("Log Scale (Y2-Axis)"); layout.addWidget(self.logscale_y2_check, 3, 0, 1, 3)
        return tab

    def create_output_settings_panel(self):
        panel = QGroupBox("5. Output Settings")
        layout = QGridLayout(panel)
        layout.addWidget(QLabel("Show Legend (key):"), 1, 0); self.key_check = QCheckBox(); self.key_check.setChecked(True); layout.addWidget(self.key_check, 1, 1)
        self.key_pos_combo = QComboBox()
        self.key_pos_combo.addItems([
            "default", "above", "top left", "top center", "top right",
            "bottom left", "bottom center", "bottom right",
            "left center", "right center", "center",
            "outside", "below"
        ])
        layout.addWidget(self.key_pos_combo, 1, 2)

        self.key_rows_check = QCheckBox("Key Max Rows:")
        self.key_rows_check.setChecked(False)
        layout.addWidget(self.key_rows_check, 2, 0)
        self.key_rows_input = QLineEdit("")
        self.key_rows_input.setPlaceholderText("自動")
        self.key_rows_input.setEnabled(False)
        layout.addWidget(self.key_rows_input, 2, 1, 1, 2)

        self.key_cols_check = QCheckBox("Key Max Cols:")
        self.key_cols_check.setChecked(False)
        layout.addWidget(self.key_cols_check, 3, 0)
        self.key_cols_input = QLineEdit("")
        self.key_cols_input.setPlaceholderText("自動")
        self.key_cols_input.setEnabled(False)
        layout.addWidget(self.key_cols_input, 3, 1, 1, 2)

        layout.addWidget(QLabel("Image Size (W x H):"), 4, 0); self.width_input = QLineEdit("800"); self.height_input = QLineEdit("600"); size_layout = QHBoxLayout(); size_layout.addWidget(self.width_input); size_layout.addWidget(QLabel("x")); size_layout.addWidget(self.height_input); layout.addLayout(size_layout, 4, 1, 1, 2)
        layout.addWidget(QLabel("Font:"), 5, 0); self.font_combo = QComboBox(); self.font_combo.addItems(["Times New Roman", "Arial", "Helvetica", "Verdana", "Courier New"]); layout.addWidget(self.font_combo, 5, 1, 1, 2)
        layout.addWidget(QLabel("Font Size:"), 6, 0); self.font_slider = QSlider(Qt.Horizontal); self.font_slider.setRange(8, 30); self.font_slider.setValue(14); self.font_label = QLabel("14"); font_layout = QHBoxLayout(); font_layout.addWidget(self.font_slider); font_layout.addWidget(self.font_label); layout.addLayout(font_layout, 6, 1, 1, 2)
        self.save_button = QPushButton("Save Graph As..."); self.save_button.clicked.connect(self.save_image); layout.addWidget(self.save_button, 7, 0, 1, 3)
        return panel

    def connect_signals(self):
        # ファイル登録セクション (ドロップゾーンとファイル選択ボタンのみ)
        self.drop_zone.fileDropped.connect(self.register_file) # 直接登録に変更
        self.findChild(QPushButton, "registerFileBrowseButton").clicked.connect(self.select_file_to_register)

        # 利用可能なファイルリスト (QComboBox) からのプロット追加
        self.available_files_combo.currentIndexChanged.connect(self.on_available_file_selection_changed)
        self.new_plot_using_input.textChanged.connect(self.update_add_plot_controls_state)
        self.new_plot_axis_combo.currentIndexChanged.connect(self.update_add_plot_controls_state)
        self.new_plot_title_input.textChanged.connect(self.update_add_plot_controls_state) 
        self.add_plot_button.clicked.connect(self.add_plot) # Add Plotボタンの接続

        # 汎用設定
        self.title_check.stateChanged.connect(self.update_title_input_state)
        self.title_check.stateChanged.connect(self.request_redraw)
        self.title_input.textChanged.connect(self.request_redraw)

        # 凡例の行と列の設定
        self.key_rows_check.stateChanged.connect(self.update_key_rows_input_state)
        self.key_rows_check.stateChanged.connect(self.request_redraw)
        self.key_rows_input.textChanged.connect(self.request_redraw)

        self.key_cols_check.stateChanged.connect(self.update_key_cols_input_state)
        self.key_cols_check.stateChanged.connect(self.request_redraw)
        self.key_cols_input.textChanged.connect(self.request_redraw)

        # 軸設定と出力設定
        for widget in [self.xlabel_input, self.ylabel_input, self.y2label_input,
                       self.xrange_min, self.xrange_max, self.yrange_min, self.yrange_max, self.y2range_min, self.y2range_max,
                       self.xtics_xoffset, self.xtics_yoffset, self.ytics_xoffset, self.ytics_yoffset,
                       self.y2tics_xoffset, self.y2tics_yoffset,
                       self.width_input, self.height_input, self.key_pos_combo, self.font_combo]:
            if isinstance(widget, QLineEdit): widget.textChanged.connect(self.request_redraw)
            else: widget.currentIndexChanged.connect(self.request_redraw)

        for widget in [self.xrange_check, self.yrange_check, self.y2range_check, self.xtics_check, self.ytics_check,
                       self.y2tics_offset_check,
                       self.logscale_x_check, self.logscale_y_check, self.logscale_y2_check, self.grid_check, self.key_check]:
            widget.stateChanged.connect(self.request_redraw)
        
        self.font_slider.valueChanged.connect(lambda v: self.font_label.setText(str(v)))
        self.font_slider.valueChanged.connect(self.request_redraw)

        # 現在のプロットタブウィジェットのシグナル接続
        self.plot_tabs.tabCloseRequested.connect(self.remove_plot_by_tab_index) # タブの✕ボタン
        self.plot_tabs.currentChanged.connect(self.on_plot_tab_changed) # タブ切り替え

    def update_style_panel_state(self):
        """スタイル設定パネルの有効/無効を、タブの選択状態に応じて切り替える (ここではスタイル設定は各タブ内にあるため不要)"""
        # このメソッドは、以前のグローバルなスタイルパネルのためにありましたが、
        # 現在は各プロットタブ内にスタイル設定があるため、通常は呼び出されません。
        pass

    def update_title_input_state(self):
        self.title_input.setEnabled(self.title_check.isChecked())

    def update_key_rows_input_state(self):
        self.key_rows_input.setEnabled(self.key_rows_check.isChecked())

    def update_key_cols_input_state(self):
        self.key_cols_input.setEnabled(self.key_cols_check.isChecked())

    def select_file_to_register(self):
        """「Browse Files...」ボタンによるファイル選択と登録"""
        file_names, _ = QFileDialog.getOpenFileNames(self, "Select Data Files to Register", "", "Data Files (*.dat *.txt);;All Files (*)")
        if file_names:
            for file_name in file_names:
                self.register_file(file_name) # ファイル登録メソッドを呼び出す

    def register_file(self, file_path):
        """ファイルをavailable_filesリストに登録し、QComboBoxを更新する
        このメソッドは、ドロップまたはBrowseによって呼び出され、
        新しいファイルが追加されたら、そのファイルをコンボボックスで自動選択します。
        """
        if not file_path or not os.path.isfile(file_path):
            return # 無効なパスは無視

        if file_path not in self.available_files:
            self.available_files.append(file_path)
            self.available_files_combo.addItem(os.path.basename(file_path), file_path) # 表示名とデータ (フルパス)
            # ここが新しいファイルが追加されたら自動選択する部分
            self.available_files_combo.setCurrentIndex(self.available_files_combo.count() - 1)
        else:
            # すでに登録されている場合は、そのファイルを再選択状態にする（必要であれば）
            # 今回は「ファイル追加時」の要望なので、新規追加時のみ自動選択とする
            pass 

    def on_available_file_selection_changed(self):
        """利用可能なファイルリスト(QComboBox)で選択が変更されたときの処理"""
        current_index = self.available_files_combo.currentIndex()
        if current_index >= 0:
            selected_file_path = self.available_files_combo.itemData(current_index)
            # 新しいプロットタイトル入力のデフォルト値を設定
            # ファイル名と拡張子を除いた部分を初期タイトルにする
            base_name = os.path.basename(selected_file_path)
            file_name_without_ext = os.path.splitext(base_name)[0]
            self.new_plot_title_input.setText(file_name_without_ext)
        else:
            self.new_plot_title_input.clear() # 選択がない場合はクリア
        self.update_add_plot_controls_state()

    def update_add_plot_controls_state(self):
        """プロット追加ボタンの有効/無効を切り替える"""
        file_selected_in_combo = self.available_files_combo.currentIndex() >= 0
        using_filled = bool(self.new_plot_using_input.text().strip())
        self.add_plot_button.setEnabled(file_selected_in_combo and using_filled)

    def request_redraw(self):
        self.update_timer.start(500)

    def add_plot(self):
        selected_file_index = self.available_files_combo.currentIndex()
        if selected_file_index < 0:
            QMessageBox.warning(self, "Warning", "プロットするファイルをプルダウンから選択してください。")
            return

        file_path = self.available_files_combo.itemData(selected_file_index)
        using = self.new_plot_using_input.text().strip()
        
        if not using:
            QMessageBox.warning(self, "Warning", "使用する列を指定してください (例: 1:2)。")
            return
            
        axis = "y1" if self.new_plot_axis_combo.currentIndex() == 0 else "y2"
        
        plot_title = self.new_plot_title_input.text().strip()
        if not plot_title:
            base_name = os.path.basename(file_path)
            file_name_without_ext = os.path.splitext(base_name)[0]
            plot_title = f"{file_name_without_ext} u {using} ({axis})"

        # 新しいプロットのデフォルトスタイルは、PlotEditorWidgetのデフォルト値に任せる
        # または、必要であればadd_plot時にも設定可能
        initial_style = { 
            "style": "lines", # 初期スタイル
            "color": "black", # 初期色
            "linestyle": "Solid", # 初期線のスタイル
            "linewidth": 1.0, # 初期線の太さ
            "pointtype": 7, # 初期点の種類 (●)
            "pointsize": 1.0 # 初期点のサイズ
        }
        
        plot_info = { 
            "file_path": file_path, 
            "using": using, 
            "axis": axis, 
            "title": plot_title, 
            "style": initial_style 
        }
        self.plots.append(plot_info)
        
        # 新しいPlotEditorWidgetを作成し、タブに追加
        plot_editor_widget = PlotEditorWidget(plot_info, self.dashtype_map)
        tab_index = self.plot_tabs.addTab(plot_editor_widget, plot_info["title"])
        self.plot_tabs.setCurrentIndex(tab_index) # 追加したタブを選択状態にする

        # プロット追加後、追加用入力欄をクリアせず、現在のファイル選択を維持
        # self.available_files_combo.setCurrentIndex(-1) # 選択をクリアしない
        self.new_plot_using_input.setText("1:2") # デフォルトに戻す
        self.new_plot_axis_combo.setCurrentIndex(0) # デフォルトに戻す
        self.new_plot_title_input.clear()
        self.update_add_plot_controls_state() # ボタンの状態を更新

        self.request_redraw()

    def remove_plot_by_tab_index(self, index):
        """タブの✕ボタンがクリックされたときにプロットを削除する"""
        if 0 <= index < len(self.plots):
            reply = QMessageBox.question(self, 'Confirm Removal', 
                                         f"プロット '{self.plots[index]['title']}' を削除しますか？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.plot_tabs.removeTab(index) # UIからタブを削除
                del self.plots[index] # データリストからプロットを削除
                self.request_redraw() # グラフを再描画

    def on_plot_tab_changed(self, index):
        """プロットタブが切り替わったときに呼ばれる"""
        # 各タブ内のPlotEditorWidgetが自身の変更を直接self.plotsに反映し、
        # request_redrawを呼び出すようになっているため、ここで特別な更新は不要。
        # ただし、プロットが全くない状態に戻った場合は表示をリセット
        if len(self.plots) == 0:
            self.plot_label.setText("Please add a plot to begin.") # 初期メッセージに戻す
            self.script_display.clear() # スクリプト表示もクリア
        else:
            self.request_redraw() # タブが切り替わったら再描画をリクエスト

    def generate_gnuplot_script(self, output_path=None, terminal_cmd=None):
        if not self.plots: return None

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
        
        if self.title_check.isChecked() and self.title_input.text():
            script += f'set title "{self.title_input.text()}"\n'

        if self.xlabel_input.text(): script += f'set xlabel "{self.xlabel_input.text()}"\n'
        if self.ylabel_input.text(): script += f'set ylabel "{self.ylabel_input.text()}"\n'
        
        has_y2 = any(p['axis'] == 'y2' for p in self.plots)
        if has_y2 and self.y2label_input.text(): script += f'set y2label "{self.y2label_input.text()}"\n'
        
        if self.xrange_check.isChecked() and self.xrange_min.text() and self.xrange_max.text(): script += f'set xrange [{self.xrange_min.text()}:{self.xrange_max.text()}]\n'
        if self.yrange_check.isChecked() and self.yrange_min.text() and self.yrange_max.text(): script += f'set yrange [{self.yrange_min.text()}:{self.yrange_max.text()}]\n'
        if has_y2 and self.y2range_check.isChecked() and self.y2range_min.text() and self.y2range_max.text(): script += f'set y2range [{self.y2range_min.text()}:{self.y2range_max.text()}]\n'
        
        if self.xtics_check.isChecked(): script += f'set xtics offset {self.xtics_xoffset.text() or "0"},{self.xtics_yoffset.text() or "0"}\n'
        if self.ytics_check.isChecked(): script += f'set ytics offset {self.ytics_xoffset.text() or "0"},{self.ytics_yoffset.text() or "0"}\n'
        
        if has_y2:
            script += 'set ytics nomirror\n'
            script += 'set y2tics\n'
            if self.y2tics_offset_check.isChecked():
                script += f'set y2tics offset {self.y2tics_xoffset.text() or "0"},{self.y2tics_yoffset.text() or "0"}\n'
        
        log_axes = ""; 
        if self.logscale_x_check.isChecked(): log_axes += "x"
        if self.logscale_y_check.isChecked(): log_axes += "y"
        if has_y2 and self.logscale_y2_check.isChecked(): log_axes += "y2"
        if log_axes: script += f'set logscale {log_axes}\n'
        else: script += 'unset logscale\n'

        if self.grid_check.isChecked(): script += 'set grid\n'
        
        if self.key_check.isChecked():
            key_command = f'set key {self.key_pos_combo.currentText()}'
            if self.key_rows_check.isChecked() and self.key_rows_input.text().isdigit():
                key_command += f' maxrows {self.key_rows_input.text()}'
            if self.key_cols_check.isChecked() and self.key_cols_input.text().isdigit():
                key_command += f' maxcols {self.key_cols_input.text()}'
            script += f'{key_command}\n'
        else: script += 'set key off\n'

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
            plot_parts.append(f'"{plot_info["file_path"]}" using {plot_info["using"]} axes {axis_cmd} {style_details} title "{plot_info["title"]}"')
        
        if plot_parts: script += "plot " + ", \\\n  ".join(plot_parts) + "\n"
            
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
            
            stdout_data, stderr_data = process.communicate(script.encode('utf-8'))
            
            if process.returncode != 0:
                self.plot_label.setText(f"Gnuplot Error:\n{stderr_data.decode('utf-8', 'ignore')}")
                return

            pixmap = QPixmap()
            if pixmap.loadFromData(stdout_data):
                self.plot_label.setPixmap(pixmap.scaled(self.plot_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.plot_label.setText("Failed to load image from Gnuplot. Check Gnuplot output or script.")
                if stderr_data:
                    self.plot_label.setText(self.plot_label.text() + f"\nStderr:\n{stderr_data.decode('utf-8', 'ignore')}")

        except FileNotFoundError:
            self.plot_label.setText("Gnuplot not found. Please ensure Gnuplot is installed and in your system's PATH.")
        except Exception as e:
            self.plot_label.setText(f"Runtime Error:\n{e}")

    def save_image(self):
        if not self.plots: QMessageBox.warning(self, "Error", "No data to plot."); return
        file_name, selected_filter = QFileDialog.getSaveFileName(self, "Save Graph As", "", "PNG Image (*.png);;SVG Image (*.svg);;PDF Document (*.pdf);;All Files (*)")
        if not file_name: return
        
        width = int(self.width_input.text() or "800"); height = int(self.height_input.text() or "900")
        font_setting = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
        
        if "svg" in selected_filter: term_cmd = f'set terminal svg size {width},{height} {font_setting}'
        elif "pdf" in selected_filter: term_cmd = f'set terminal pdfcairo size {width/100.0},{height/100.0} {font_setting}'
        else: term_cmd = f'set terminal pngcairo size {width},{height} enhanced {font_setting}'
        
        script = self.generate_gnuplot_script(output_path=file_name, terminal_cmd=term_cmd)
        
        if not script: QMessageBox.critical(self, "Error", "Failed to generate script."); return
        try:
            process = subprocess.Popen(['gnuplot'], 
                                       stdin=subprocess.PIPE, 
                                       stderr=subprocess.PIPE, 
                                       text=True, 
                                       encoding='utf-8',
                                       creationflags=CREATE_NO_WINDOW)
            _, stderr = process.communicate(script)
            if process.returncode == 0: QMessageBox.information(self, "Success", f"Graph saved to {file_name}")
            else: QMessageBox.critical(self, "Gnuplot Error", f"Failed to save graph.\n\n{stderr}")
        except FileNotFoundError:
            QMessageBox.critical(self, "Gnuplot Not Found", "Gnuplotが見つかりません。Gnuplotがインストールされており、システムのPATHが設定されていることを確認してください。")
        except Exception as e: QMessageBox.critical(self, "Runtime Error", f"An error occurred.\n\n{e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.plot_tabs.count() > 0: # プロットタブがある場合のみ再描画をリクエスト
            self.request_redraw()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = GnuplotGUIY2Axis()
    window.show()
    sys.exit(app.exec())