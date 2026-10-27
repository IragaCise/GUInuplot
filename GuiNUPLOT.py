import sys
import os
import subprocess
import json
import hashlib
import math
import tempfile
import threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QCheckBox, QFileDialog, QSlider,
    QGridLayout, QTextEdit, QComboBox, QMessageBox, QDoubleSpinBox,
    QTabWidget, QGroupBox, QScrollArea, QSizePolicy, QSpinBox, QInputDialog
)
from PySide6.QtGui import QFont, QPixmap, QAction
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRunnable, QThreadPool, QProcess

# Windowsで実行する際にコンソールウィンドウを非表示にするためのフラグです
CREATE_NO_WINDOW = 0
if os.name == 'nt':
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW


class PreviewCancelled(Exception):
    """古いプレビューの準備が取り消された場合。"""


class PreviewDataCache:
    """設定を変更しても再利用できる、間引き済みテキストデータのキャッシュ。"""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.statistics = {}  # (path, size, mtime_ns) -> (data_rows, scans)
        self.sampled = {}     # (signature, max_points, is_3d) -> path

    @staticmethod
    def _is_data(line):
        stripped = line.strip()
        return bool(stripped) and not line.lstrip().startswith(b'#')

    @staticmethod
    def _check_cancel(cancel_event, i):
        if i % 8192 == 0 and cancel_event.is_set():
            raise PreviewCancelled()

    def preview_path(self, source_path, max_points, is_3d, cancel_event):
        # ファイルが更新された場合は size / mtime_ns が変わるので自動的に作り直す。
        source_path = os.path.abspath(source_path)
        stat = os.stat(source_path)
        signature = (source_path, stat.st_size, stat.st_mtime_ns)
        stats = self.statistics.get(signature)
        if stats is None:
            data_rows, scans = 0, 0
            in_scan = False
            with open(source_path, 'rb') as src:
                for i, line in enumerate(src):
                    self._check_cancel(cancel_event, i)
                    if not line.strip():
                        in_scan = False
                    elif self._is_data(line):
                        data_rows += 1
                        if not in_scan:
                            scans += 1
                            in_scan = True
            stats = (data_rows, scans)
            self.statistics[signature] = stats

        data_rows, scans = stats
        if data_rows <= max_points:
            return source_path
        key = (signature, max_points, is_3d)
        cached = self.sampled.get(key)
        if cached and os.path.isfile(cached):
            return cached

        # 格子型3Dデータは空行が走査線を分けるので、行方向と走査線方向の両方を減らす。
        # 空行のない点群、2Dデータは全体を等間隔で間引く。
        grid = is_3d and scans > 1
        if grid:
            ratio = data_rows / max_points
            scan_step = min(scans, max(1, math.ceil(math.sqrt(ratio))))
            row_step = max(1, math.ceil(ratio / scan_step))
        else:
            scan_step = 1
            row_step = max(1, math.ceil(data_rows / max_points))

        hash_key = repr(key).encode('utf-8')
        digest = hashlib.sha256(hash_key).hexdigest()[:24]
        output_path = os.path.join(self.cache_dir, f'preview_{digest}.dat')
        part_path = output_path + '.part'
        try:
            with open(source_path, 'rb') as src, open(part_path, 'wb') as dst:
                data_index = 0
                scan_index = -1
                row_in_scan = 0
                at_scan_start = True
                consecutive_blanks = 0
                block_break_pending = False
                last_written_scan = -1
                pending_separator = 0
                has_written = False
                for i, line in enumerate(src):
                    self._check_cancel(cancel_event, i)
                    if not line.strip():
                        if grid:
                            consecutive_blanks += 1
                            at_scan_start = True
                        else:
                            pending_separator = min(2, pending_separator + 1)
                        continue
                    if not self._is_data(line):
                        continue  # コメントは数値データではないためコピーしない

                    if grid:
                        if at_scan_start:
                            if consecutive_blanks >= 2:
                                block_break_pending = True
                            consecutive_blanks = 0
                            scan_index += 1
                            row_in_scan = 0
                            at_scan_start = False
                        use_row = scan_index % scan_step == 0 and row_in_scan % row_step == 0
                        if use_row:
                            if has_written and last_written_scan != scan_index:
                                dst.write(b'\n\n' if block_break_pending else b'\n')
                            dst.write(line if line.endswith(b'\n') else line + b'\n')
                            last_written_scan = scan_index
                            block_break_pending = False
                            has_written = True
                        row_in_scan += 1
                    else:
                        if data_index % row_step == 0:
                            if has_written and pending_separator:
                                dst.write(b'\n' * pending_separator)
                            dst.write(line if line.endswith(b'\n') else line + b'\n')
                            pending_separator = 0
                            has_written = True
                        data_index += 1
            if cancel_event.is_set():
                raise PreviewCancelled()
            os.replace(part_path, output_path)
            self.sampled[key] = output_path
            return output_path
        finally:
            if os.path.exists(part_path):
                os.remove(part_path)


class PreviewDataSignals(QObject):
    finished = Signal(int, object, str)


class PreviewDataTask(QRunnable):
    """GUIスレッドを止めずに、必要なプレビュー用ファイルを用意する。"""

    def __init__(self, cache, files, max_points, is_3d, token, cancel_event):
        super().__init__()
        self.cache = cache
        self.files = files
        self.max_points = max_points
        self.is_3d = is_3d
        self.token = token
        self.cancel_event = cancel_event
        self.signals = PreviewDataSignals()

    def run(self):
        try:
            replacements = {}
            for source_path in self.files:
                if self.cancel_event.is_set():
                    return
                replacements[source_path] = self.cache.preview_path(
                    source_path, self.max_points, self.is_3d, self.cancel_event
                )
            if not self.cancel_event.is_set():
                self.signals.finished.emit(self.token, replacements, '')
        except PreviewCancelled:
            pass
        except Exception as exc:
            if not self.cancel_event.is_set():
                self.signals.finished.emit(self.token, {}, str(exc))


class DropLabel(QLabel):
    """ファイルがドロップされたことを通知するカスタムラベルウィジェット"""
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

class PlotEditorWidget(QWidget):
    """各プロットの設定を管理するためのタブ内ウィジェット"""
    plotChanged = Signal()
    titleChanged = Signal(str)

    def __init__(self, plot_info: dict, dashtype_map: dict, parent=None):
        super().__init__(parent)
        self.plot_info = plot_info
        self.dashtype_map = dashtype_map
        self.init_ui()
        self.load_info_to_ui()
        self.connect_signals()

    def init_ui(self):
        """UI要素を初期化"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        details_group = QGroupBox("Plot Details")
        details_layout = QGridLayout(details_group)
        details_layout.addWidget(QLabel("Title (Legend):"), 0, 0)
        self.title_input = QLineEdit()
        details_layout.addWidget(self.title_input, 0, 1)
        
        details_layout.addWidget(QLabel("Using:"), 1, 0)
        self.using_input = QLineEdit() 
        details_layout.addWidget(self.using_input, 1, 1)
        
        details_layout.addWidget(QLabel("File:"), 2, 0)
        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        details_layout.addWidget(self.file_label, 2, 1)

        # モデルモード設定
        self.is_model_check = QCheckBox("Static Model Mode (No CB influence)")
        self.is_model_check.setToolTip("チェックを入れると、このプロットを「物体モデル」として扱います。\nカラーバーの範囲計算から除外され、単色で表示されます。")
        details_layout.addWidget(self.is_model_check, 3, 0, 1, 2)

        self.normal_style_group = QGroupBox("Plot Style")
        self.normal_style_group.setCheckable(False)
        grid_layout = QGridLayout(self.normal_style_group)
        grid_layout.addWidget(QLabel("Style:"), 0, 0)
        self.style_combo = QComboBox()
        grid_layout.addWidget(self.style_combo, 0, 1)
        grid_layout.addWidget(QLabel("Point Type:"), 1, 0)
        self.pointtype_combo = QComboBox()
        self.pointtype_combo.addItems(["1: +", "2: x", "3: *", "4: □", "5: ■", "6: ○", "7: ●", "8: △", "9: ▲"])
        grid_layout.addWidget(self.pointtype_combo, 1, 1)
        grid_layout.addWidget(QLabel("Point Size:"), 2, 0)
        self.pointsize_spinbox = QDoubleSpinBox()
        self.pointsize_spinbox.setRange(0.1, 20.0); self.pointsize_spinbox.setValue(1.0); self.pointsize_spinbox.setSingleStep(0.1)
        grid_layout.addWidget(self.pointsize_spinbox, 2, 1)
        
        self.line_style_group = QGroupBox("Line/Vector/Color Properties")
        line_style_layout = QGridLayout(self.line_style_group)
        self.color_from_value_check = QCheckBox("Color from Data (Palette)")
        line_style_layout.addWidget(self.color_from_value_check, 0, 0, 1, 2)
        line_style_layout.addWidget(QLabel("Color Expr:"), 1, 0)
        self.color_value_input = QLineEdit()
        line_style_layout.addWidget(self.color_value_input, 1, 1)
        line_style_layout.addWidget(QLabel("Color:"), 2, 0)
        self.color_combo = QComboBox()
        self.color_combo.addItems(["black", "red", "green", "blue", "magenta", "cyan", "yellow", "orange", "brown", "gray", "dark-gray", "light-gray"])
        line_style_layout.addWidget(self.color_combo, 2, 1)
        line_style_layout.addWidget(QLabel("Line Style:"), 3, 0)
        self.linestyle_combo = QComboBox()
        self.linestyle_combo.addItems(self.dashtype_map.keys())
        line_style_layout.addWidget(self.linestyle_combo, 3, 1)
        line_style_layout.addWidget(QLabel("Line Width:"), 4, 0)
        self.linewidth_spinbox = QDoubleSpinBox()
        self.linewidth_spinbox.setRange(0.1, 20.0); self.linewidth_spinbox.setValue(1.0); self.linewidth_spinbox.setSingleStep(0.1)
        line_style_layout.addWidget(self.linewidth_spinbox, 4, 1)

        self.vector_style_group = QGroupBox("Vector Options")
        vec_layout = QGridLayout(self.vector_style_group)
        vec_layout.addWidget(QLabel("Head:"), 0, 0)
        self.vector_nohead_check = QCheckBox("No Arrow Head")
        vec_layout.addWidget(self.vector_nohead_check, 0, 1)
        vec_layout.addWidget(QLabel("Head Style:"), 1, 0)
        self.vector_headstyle_combo = QComboBox(); self.vector_headstyle_combo.addItems(["Default", "filled", "empty"])
        vec_layout.addWidget(self.vector_headstyle_combo, 1, 1)
        vec_layout.addWidget(QLabel("Head Size (len,ang,back_ang):"), 2, 0)
        self.vector_headsize_input = QLineEdit("0.1,15,60")
        vec_layout.addWidget(self.vector_headsize_input, 2, 1)
        vec_layout.addWidget(QLabel("Length Scale:"), 3, 0)
        self.vector_length_scale_spinbox = QDoubleSpinBox()
        self.vector_length_scale_spinbox.setRange(0.01, 10000000.0); self.vector_length_scale_spinbox.setValue(1.0); self.vector_length_scale_spinbox.setSingleStep(0.1); self.vector_length_scale_spinbox.setDecimals(2)
        vec_layout.addWidget(self.vector_length_scale_spinbox, 3, 1)
        self.vector_normalize_check = QCheckBox("Normalize Vectors (using Color Expr)")
        vec_layout.addWidget(self.vector_normalize_check, 4, 0, 1, 2)
        
        layout.addWidget(details_group)
        layout.addWidget(self.normal_style_group)
        layout.addWidget(self.vector_style_group)
        layout.addWidget(self.line_style_group)
        layout.addStretch(1)

    def load_info_to_ui(self):
        is_vector = self.plot_info.get("is_vector", False)
        plot_style = self.plot_info.get("style", {})
        vec_opts = plot_style.get("vector_options", {})
        
        for widget in self.findChildren(QWidget): widget.blockSignals(True)

        self.title_input.setText(self.plot_info.get("title", ""))
        self.using_input.setText(self.plot_info.get("using", ""))
        self.file_label.setText(os.path.basename(self.plot_info.get("path", "")))
        
        self.is_model_check.setChecked(self.plot_info.get("is_model_mode", False))

        self.style_combo.clear()
        is_3d = self.plot_info.get("is_3d_mode", False)
        base_styles = ["lines", "points", "linespoints", "dots", "impulses"]
        if is_3d: self.style_combo.addItems(base_styles + ["pm3d"])
        else: self.style_combo.addItems(base_styles + ["steps"])

        self.normal_style_group.setVisible(not is_vector)
        self.vector_style_group.setVisible(is_vector)

        self.style_combo.setCurrentText(plot_style.get("style", "lines"))
        self.pointtype_combo.setCurrentIndex(plot_style.get("pointtype", 1) - 1)
        self.pointsize_spinbox.setValue(plot_style.get("pointsize", 1.0))

        self.color_from_value_check.setChecked(plot_style.get("color_from_value", False))
        self.color_value_input.setText(plot_style.get("color_expression", ""))
        self.color_combo.setCurrentText(plot_style.get("color", "black"))
        self.linestyle_combo.setCurrentText(plot_style.get("linestyle", "Solid"))
        self.linewidth_spinbox.setValue(plot_style.get("linewidth", 1.0))
        
        self.vector_nohead_check.setChecked(vec_opts.get("nohead", False))
        self.vector_headstyle_combo.setCurrentText(vec_opts.get("head_style", "Default"))
        self.vector_headsize_input.setText(vec_opts.get("head_size", "0.1,15,60"))
        self.vector_length_scale_spinbox.setValue(vec_opts.get("length_scale", 1.0))
        self.vector_normalize_check.setChecked(vec_opts.get("normalize", False))

        self.toggle_color_controls()
        self.toggle_model_mode_ui()

        for widget in self.findChildren(QWidget): widget.blockSignals(False)

    def connect_signals(self):
        self.title_input.textChanged.connect(self.update_plot_info)
        self.title_input.textChanged.connect(self.titleChanged.emit)
        self.using_input.textChanged.connect(self.update_plot_info)
        self.is_model_check.stateChanged.connect(self.update_plot_info)
        self.is_model_check.stateChanged.connect(self.toggle_model_mode_ui)
        self.style_combo.currentIndexChanged.connect(self.update_plot_info)
        self.pointtype_combo.currentIndexChanged.connect(self.update_plot_info)
        self.pointsize_spinbox.valueChanged.connect(self.update_plot_info)
        self.color_from_value_check.stateChanged.connect(self.update_plot_info)
        self.color_from_value_check.stateChanged.connect(self.toggle_color_controls)
        self.color_value_input.textChanged.connect(self.update_plot_info)
        self.color_combo.currentIndexChanged.connect(self.update_plot_info)
        self.linestyle_combo.currentIndexChanged.connect(self.update_plot_info)
        self.linewidth_spinbox.valueChanged.connect(self.update_plot_info)
        self.vector_nohead_check.stateChanged.connect(self.update_plot_info)
        self.vector_headstyle_combo.currentIndexChanged.connect(self.update_plot_info)
        self.vector_headsize_input.textChanged.connect(self.update_plot_info)
        self.vector_length_scale_spinbox.valueChanged.connect(self.update_plot_info)
        self.vector_normalize_check.stateChanged.connect(self.update_plot_info)

    def update_plot_info(self):
        style_dict = self.plot_info["style"]
        is_vector = self.plot_info.get("is_vector", False)
        
        self.plot_info["title"] = self.title_input.text()
        self.plot_info["using"] = self.using_input.text()
        self.plot_info["is_model_mode"] = self.is_model_check.isChecked()

        if is_vector:
            style_dict["vector_options"] = {
                "nohead": self.vector_nohead_check.isChecked(), "head_style": self.vector_headstyle_combo.currentText(),
                "head_size": self.vector_headsize_input.text(), "length_scale": self.vector_length_scale_spinbox.value(),
                "normalize": self.vector_normalize_check.isChecked()
            }
        else:
            style_dict["style"] = self.style_combo.currentText()
            style_dict["pointtype"] = self.pointtype_combo.currentIndex() + 1
            style_dict["pointsize"] = self.pointsize_spinbox.value()
        
        style_dict["color"] = self.color_combo.currentText()
        style_dict["linestyle"] = self.linestyle_combo.currentText()
        style_dict["linewidth"] = self.linewidth_spinbox.value()
        style_dict["color_from_value"] = self.color_from_value_check.isChecked()
        style_dict["color_expression"] = self.color_value_input.text()
        
        self.plotChanged.emit()

    def toggle_color_controls(self):
        use_palette = self.color_from_value_check.isChecked()
        if self.is_model_check.isChecked():
            self.color_combo.setEnabled(True)
            self.color_value_input.setEnabled(False)
            self.color_from_value_check.setEnabled(False)
        else:
            self.color_from_value_check.setEnabled(True)
            self.color_combo.setEnabled(not use_palette)
            self.color_value_input.setEnabled(use_palette)

    def toggle_model_mode_ui(self):
        is_model = self.is_model_check.isChecked()
        if is_model:
            self.color_from_value_check.setChecked(False)
            if self.color_combo.currentText() == "black":
                self.color_combo.setCurrentText("gray")
            if not self.plot_info.get("is_vector", False):
                self.style_combo.setCurrentText("lines")
        self.toggle_color_controls()


class GnuplotGUIY2Axis(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("GUInuplot (Integrated)")
        self.setGeometry(100, 100, 1600, 950)
        self.plots = []
        self.current_selected_file_path = None
        self.current_mode = "2d"
        self.column_spinboxes = []
        self.dashtype_map = {"Solid": 1, "Dashed": 2, "Dotted": 3, "Dash-Dot": 4}
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.redraw_plot)
        # プレビュー描画は非同期で実行。古い描画は設定変更時に破棄する。
        self._preview_generation = 0
        self._preview_process = None
        self._preview_cancel_event = threading.Event()
        self._last_preview_pixmap = QPixmap()
        self._preview_tempdir = tempfile.TemporaryDirectory(prefix='guinuplot_preview_')
        self._preview_cache = PreviewDataCache(self._preview_tempdir.name)
        self._preview_pool = QThreadPool(self)
        self._preview_pool.setMaxThreadCount(1)
        self.init_ui()
        
        # 起動時に設定を自動ロードする
        self.auto_load_settings()

    def init_ui(self):
        self.create_menu_bar()
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(580)
        control_panel = QWidget()
        self.control_layout = QVBoxLayout(control_panel)
        self.control_layout.addWidget(self.create_mode_selection_panel())
        self.control_layout.addWidget(self.create_plot_management_panel())
        self.control_layout.addWidget(self.create_plot_tabs_panel())
        self.control_layout.addWidget(self.create_general_settings_panel())
        self.control_layout.addWidget(self.create_axis_settings_panel())
        self.view_settings_panel = self.create_view_settings_panel()
        self.control_layout.addWidget(self.view_settings_panel)
        self.control_layout.addWidget(self.create_output_settings_panel())
        self.control_layout.addWidget(self.create_preview_settings_panel())
        self.control_layout.addWidget(QLabel("Gnuplot Command Preview:"))
        self.script_display = QTextEdit()
        self.script_display.setReadOnly(True)
        self.script_display.setFont(QFont("Courier New", 10))
        self.control_layout.addWidget(self.script_display)
        self.control_layout.addStretch(1)
        scroll_area.setWidget(control_panel)
        self.plot_label = QLabel("Please add a plot to begin.")
        self.plot_label.setAlignment(Qt.AlignCenter)
        self.plot_label.setStyleSheet("background-color: #ffffff;")
        main_layout.addWidget(scroll_area)
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.plot_label, 1)
        self.preview_status = QLabel('')
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        main_layout.addWidget(preview_container, 1)
        self.connect_signals()
        self.on_mode_changed()

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        export_action = QAction("Export Project...", self)
        export_action.setToolTip("Save PNG, .gp, and .c files into a new folder.")
        export_action.triggered.connect(self.export_project)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()

        save_graph_action = QAction("Save Graph As...", self)
        save_graph_action.setToolTip("Save the current graph to an image file (PNG, SVG, PDF).")
        save_graph_action.triggered.connect(self.save_image)
        file_menu.addAction(save_graph_action)
        
        save_script_action = QAction("Save Script As (.gp)...", self)
        save_script_action.setToolTip("Save the Gnuplot commands to a .gp file.")
        save_script_action.triggered.connect(self.save_gp_file)
        file_menu.addAction(save_script_action)
        
        save_c_action = QAction("Save for C Language As (.c)...", self)
        save_c_action.setToolTip("Save commands as a C source file using popen.")
        save_c_action.triggered.connect(self.save_for_c)
        file_menu.addAction(save_c_action)

        file_menu.addSeparator()

        save_settings_action = QAction("Save Settings...", self)
        save_settings_action.setToolTip("Save the current graph settings to a file.")
        save_settings_action.triggered.connect(self.save_settings)
        file_menu.addAction(save_settings_action)

        load_settings_action = QAction("Load Settings...", self)
        load_settings_action.setToolTip("Load graph settings from a file.")
        load_settings_action.triggered.connect(self.load_settings)
        file_menu.addAction(load_settings_action)

    def create_mode_selection_panel(self, *args, **kwargs):
        panel = QGroupBox("Plot Mode")
        layout = QHBoxLayout(panel)
        layout.addWidget(QLabel("Mode:"))
        self.plot_mode_combo = QComboBox()
        self.plot_mode_combo.addItems(["2D Plot", "3D Plot (splot)"])
        layout.addWidget(self.plot_mode_combo, 1)
        return panel

    def create_plot_management_panel(self, *args, **kwargs):
        panel = QGroupBox("1. Add New Plot")
        add_layout = QGridLayout(panel)
        self.drop_zone = DropLabel()
        add_layout.addWidget(self.drop_zone, 0, 0, 1, 3)
        add_layout.addWidget(QLabel("File:"), 1, 0)
        self.new_plot_file_input = QLineEdit()
        self.new_plot_file_input.setReadOnly(True)
        self.new_plot_file_input.setPlaceholderText("ファイルを選択 or ドロップ")
        add_layout.addWidget(self.new_plot_file_input, 1, 1)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.select_plot_file)
        add_layout.addWidget(browse_button, 1, 2)
        
        self.add_as_vector_check = QCheckBox("Add as Vector Plot")
        add_layout.addWidget(self.add_as_vector_check, 2, 0, 1, 3)
        
        self.add_as_model_check = QCheckBox("Add as Static Object (Model)")
        self.add_as_model_check.setToolTip("物体モデル（ワイヤーフレーム等）として追加します。\nカラーバーの値に影響を与えず、単色（グレー）で表示されます。")
        add_layout.addWidget(self.add_as_model_check, 3, 0, 1, 3)

        add_layout.addWidget(QLabel("Columns (using):"), 4, 0)
        self.column_input_layout = QHBoxLayout()
        self.column_input_layout.setSpacing(5)
        add_layout.addLayout(self.column_input_layout, 4, 1, 1, 2)
        self.target_axis_label = QLabel("Target Axis:")
        add_layout.addWidget(self.target_axis_label, 5, 0)
        self.new_plot_axis_combo = QComboBox()
        self.new_plot_axis_combo.addItems(["Y1-Axis", "Y2-Axis"])
        add_layout.addWidget(self.new_plot_axis_combo, 5, 1, 1, 2)
        add_plot_button = QPushButton("Add Plot to Tabs")
        add_plot_button.clicked.connect(self.add_plot)
        add_layout.addWidget(add_plot_button, 6, 0, 1, 3)
        return panel

    def create_plot_tabs_panel(self, *args, **kwargs):
        panel = QGroupBox("2. Current Plots (Edit in Tabs)")
        layout = QVBoxLayout(panel)
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setTabsClosable(True)
        self.plot_tabs.setMovable(True)
        self.plot_tabs.setMinimumHeight(350)
        layout.addWidget(self.plot_tabs)
        return panel

    def create_general_settings_panel(self, *args, **kwargs):
        panel = QGroupBox("3. General Graph Settings")
        layout = QGridLayout(panel)
        self.title_check = QCheckBox("Graph Title:")
        self.title_check.setChecked(False)
        layout.addWidget(self.title_check, 0, 0)
        self.title_input = QLineEdit("My Graph Title")
        self.title_input.setEnabled(False)
        layout.addWidget(self.title_input, 0, 1)

        # 枠線（ボーダー・目盛り線）の太さ
        layout.addWidget(QLabel("Frame/Tics Line Width:"), 1, 0)
        self.border_width_spinbox = QDoubleSpinBox()
        self.border_width_spinbox.setRange(0.1, 10.0)
        self.border_width_spinbox.setValue(1.0)
        self.border_width_spinbox.setSingleStep(0.1)
        layout.addWidget(self.border_width_spinbox, 1, 1)

        return panel

    def create_axis_settings_panel(self, *args, **kwargs):
        panel = QGroupBox("4. Axis Settings")
        panel_layout = QVBoxLayout(panel)
        self.axis_tabs = QTabWidget()
        self.axis_tabs.addTab(self.create_xaxis_tab(), "X-Axis")
        self.axis_tabs.addTab(self.create_y1axis_tab(), "Y1-Axis")
        self.y2_axis_tab = self.create_y2axis_tab()
        self.axis_tabs.addTab(self.y2_axis_tab, "Y2-Axis")
        self.z_axis_tab = self.create_zaxis_tab()
        self.axis_tabs.addTab(self.z_axis_tab, "Z-Axis")
        panel_layout.addWidget(self.axis_tabs)
        return panel

    def create_xaxis_tab(self, *args, **kwargs):
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

        # グリッド設定と太さ
        grid_layout = QHBoxLayout()
        self.grid_check = QCheckBox("Show Grid")
        grid_layout.addWidget(self.grid_check)
        
        self.grid_width_label = QLabel("Grid Width:")
        self.grid_width_label.setEnabled(False)
        grid_layout.addWidget(self.grid_width_label)

        self.grid_width_spinbox = QDoubleSpinBox()
        self.grid_width_spinbox.setRange(0.1, 10.0)
        self.grid_width_spinbox.setValue(1.0)
        self.grid_width_spinbox.setSingleStep(0.1)
        self.grid_width_spinbox.setEnabled(False)
        grid_layout.addWidget(self.grid_width_spinbox)
        grid_layout.addStretch(1)
        
        layout.addLayout(grid_layout, 4, 0, 1, 3)

        return tab

    def create_y1axis_tab(self, *args, **kwargs):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("Y-Axis Label:"), 0, 0)
        self.ylabel_input = QLineEdit("Y-Axis")
        layout.addWidget(self.ylabel_input, 0, 1, 1, 2)
        self.yrange_check = QCheckBox("yrange")
        self.yrange_min = QLineEdit()
        self.yrange_max = QLineEdit()
        layout.addWidget(self.yrange_check, 1, 0)
        layout.addWidget(self.yrange_min, 1, 1)
        layout.addWidget(self.yrange_max, 1, 2)
        self.ytics_check = QCheckBox("ytics offset")
        self.ytics_xoffset = QLineEdit("-1")
        self.ytics_yoffset = QLineEdit("0")
        ytics_layout = QHBoxLayout()
        ytics_layout.addWidget(self.ytics_xoffset)
        ytics_layout.addWidget(QLabel(","))
        ytics_layout.addWidget(self.ytics_yoffset)
        layout.addWidget(self.ytics_check, 2, 0)
        layout.addLayout(ytics_layout, 2, 1, 1, 2)
        self.logscale_y_check = QCheckBox("Log Scale (Y-Axis)")
        layout.addWidget(self.logscale_y_check, 3, 0, 1, 3)
        return tab

    def create_y2axis_tab(self, *args, **kwargs):
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

    def create_zaxis_tab(self, *args, **kwargs):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("Z-Axis Label:"), 0, 0)
        self.zlabel_input = QLineEdit("Z-Axis")
        layout.addWidget(self.zlabel_input, 0, 1, 1, 2)
        self.zrange_check = QCheckBox("zrange")
        self.zrange_min = QLineEdit()
        self.zrange_max = QLineEdit()
        layout.addWidget(self.zrange_check, 1, 0)
        layout.addWidget(self.zrange_min, 1, 1)
        layout.addWidget(self.zrange_max, 1, 2)
        self.ztics_check = QCheckBox("ztics offset")
        self.ztics_xoffset = QLineEdit("0")
        self.ztics_yoffset = QLineEdit("0")
        ztics_layout = QHBoxLayout()
        ztics_layout.addWidget(self.ztics_xoffset)
        ztics_layout.addWidget(QLabel(","))
        ztics_layout.addWidget(self.ztics_yoffset)
        layout.addWidget(self.ztics_check, 2, 0)
        layout.addLayout(ztics_layout, 2, 1, 1, 2)
        self.logscale_z_check = QCheckBox("Log Scale (Z-Axis)")
        layout.addWidget(self.logscale_z_check, 3, 0, 1, 3)
        return tab

    def create_view_settings_panel(self, *args, **kwargs):
        panel = QGroupBox("5. View & Map Settings (3D)")
        layout = QGridLayout(panel)
        layout.addWidget(QLabel("Rotate X:"), 0, 0)
        self.view_rot_x_slider = QSlider(Qt.Horizontal)
        self.view_rot_x_slider.setRange(0, 180)
        self.view_rot_x_slider.setValue(60)
        self.view_rot_x_label = QLabel("60")
        layout.addWidget(self.view_rot_x_slider, 0, 1)
        layout.addWidget(self.view_rot_x_label, 0, 2)
        layout.addWidget(QLabel("Rotate Z:"), 1, 0)
        self.view_rot_z_slider = QSlider(Qt.Horizontal)
        self.view_rot_z_slider.setRange(0, 360)
        self.view_rot_z_slider.setValue(30)
        self.view_rot_z_label = QLabel("30")
        layout.addWidget(self.view_rot_z_slider, 1, 1)
        layout.addWidget(self.view_rot_z_label, 1, 2)
        self.pm3d_check = QCheckBox("Enable pm3d (for surfaces)")
        self.pm3d_check.setChecked(True)
        layout.addWidget(self.pm3d_check, 2, 0, 1, 3)
        
        # --- xyplane (z-axis floor) settings ---
        self.xyplane_check = QCheckBox("Fix XY Plane at Z=")
        self.xyplane_check.setToolTip("Enable this to force the XY plane to a specific Z-value (e.g., 0).\nPrevents the axis lines from extending below the floor.")
        self.xyplane_input = QLineEdit("0")
        self.xyplane_input.setEnabled(False)
        self.xyplane_input.setFixedWidth(60)
        xyplane_layout = QHBoxLayout()
        xyplane_layout.addWidget(self.xyplane_check)
        xyplane_layout.addWidget(self.xyplane_input)
        xyplane_layout.addStretch(1)
        layout.addLayout(xyplane_layout, 3, 0, 1, 3)
        # ---------------------------------------

        return panel

    def create_output_settings_panel(self, *args, **kwargs):
        panel = QGroupBox("6. Output Settings")
        layout = QVBoxLayout(panel)
        general_group = QGroupBox("General Output")
        general_layout = QGridLayout(general_group)
        general_layout.addWidget(QLabel("Image Size (W x H):"), 0, 0)
        self.width_input = QLineEdit("800")
        self.height_input = QLineEdit("600")
        size_layout_gen = QHBoxLayout()
        size_layout_gen.addWidget(self.width_input)
        size_layout_gen.addWidget(QLabel("x"))
        size_layout_gen.addWidget(self.height_input)
        general_layout.addLayout(size_layout_gen, 0, 1, 1, 2)
        general_layout.addWidget(QLabel("Font:"), 1, 0)
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Times New Roman", "Arial", "Helvetica", "Verdana", "Courier New"])
        general_layout.addWidget(self.font_combo, 1, 1, 1, 2)
        general_layout.addWidget(QLabel("Font Size:"), 2, 0)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 30)
        self.font_slider.setValue(14)
        self.font_label = QLabel("14")
        font_layout = QHBoxLayout()
        font_layout.addWidget(self.font_slider)
        font_layout.addWidget(self.font_label)
        general_layout.addLayout(font_layout, 2, 1, 1, 2)
        key_group = QGroupBox("Legend (Key) Settings")
        key_layout = QGridLayout(key_group)
        self.key_check = QCheckBox("Show Legend (key)")
        self.key_check.setChecked(True)
        key_layout.addWidget(self.key_check, 0, 0, 1, 3)
        key_layout.addWidget(QLabel("Position:"), 1, 0)
        self.key_pos_combo = QComboBox()
        self.key_pos_combo.addItems(["default", "above", "top left", "top center", "top right", "bottom left", "bottom center", "bottom right", "left center", "right center", "center", "outside", "below"])
        key_layout.addWidget(self.key_pos_combo, 1, 1, 1, 2)
        key_layout.addWidget(QLabel("Max Rows:"), 2, 0)
        self.key_maxrows_spinbox = QSpinBox()
        self.key_maxrows_spinbox.setMinimum(0)
        self.key_maxrows_spinbox.setToolTip("凡例の最大の行数を指定（0で自動）")
        key_layout.addWidget(self.key_maxrows_spinbox, 2, 1, 1, 2)
        key_layout.addWidget(QLabel("Max Columns:"), 3, 0)
        self.key_maxcols_spinbox = QSpinBox()
        self.key_maxcols_spinbox.setMinimum(0)
        self.key_maxcols_spinbox.setToolTip("凡例の最大の列数を指定（0で自動）")
        key_layout.addWidget(self.key_maxcols_spinbox, 3, 1, 1, 2)
        cb_group = QGroupBox("Color Box Settings")
        cb_layout = QGridLayout(cb_group)
        self.colorbar_check = QCheckBox("Show Color Box")
        self.colorbar_check.setChecked(True)
        cb_layout.addWidget(self.colorbar_check, 0, 0, 1, 3)
        cb_layout.addWidget(QLabel("CB Label:"), 1, 0)
        self.cblabel_input = QLineEdit("Magnitude")
        cb_layout.addWidget(self.cblabel_input, 1, 1, 1, 2)
        
        self.cb_format_10_power_check = QCheckBox("数値を 10^x 形式で表示")
        self.cb_format_10_power_check.setToolTip("チェックを入れると、カラーバーの数値を 10の乗数形式 (1.2 x 10^5) で表示します。")
        cb_layout.addWidget(self.cb_format_10_power_check, 2, 0, 1, 3)

        self.cbrange_check = QCheckBox("Set CB Range")
        cb_layout.addWidget(self.cbrange_check, 3, 0)
        self.cbrange_min = QLineEdit()
        cb_layout.addWidget(self.cbrange_min, 3, 1)
        self.cbrange_max = QLineEdit()
        cb_layout.addWidget(self.cbrange_max, 3, 2)
        self.cbsize_check = QCheckBox("Customize Position/Size")
        cb_layout.addWidget(self.cbsize_check, 4, 0, 1, 3)
        cb_layout.addWidget(QLabel("Origin (x,y):"), 5, 0)
        origin_layout = QHBoxLayout()
        self.cb_origin_x_spinbox = QDoubleSpinBox()
        self.cb_origin_x_spinbox.setRange(0, 1)
        self.cb_origin_x_spinbox.setValue(0.92)
        self.cb_origin_x_spinbox.setSingleStep(0.01)
        self.cb_origin_x_spinbox.setDecimals(2)
        origin_layout.addWidget(self.cb_origin_x_spinbox)
        self.cb_origin_y_spinbox = QDoubleSpinBox()
        self.cb_origin_y_spinbox.setRange(0, 1)
        self.cb_origin_y_spinbox.setValue(0.1)
        self.cb_origin_y_spinbox.setSingleStep(0.01)
        self.cb_origin_y_spinbox.setDecimals(2)
        origin_layout.addWidget(self.cb_origin_y_spinbox)
        cb_layout.addLayout(origin_layout, 5, 1, 1, 2)
        cb_layout.addWidget(QLabel("Size (w,h):"), 6, 0)
        size_layout_cb = QHBoxLayout()
        self.cb_size_w_spinbox = QDoubleSpinBox()
        self.cb_size_w_spinbox.setRange(0.01, 0.5)
        self.cb_size_w_spinbox.setValue(0.04)
        self.cb_size_w_spinbox.setSingleStep(0.01)
        self.cb_size_w_spinbox.setDecimals(2)
        size_layout_cb.addWidget(self.cb_size_w_spinbox)
        self.cb_size_h_spinbox = QDoubleSpinBox()
        self.cb_size_h_spinbox.setRange(0.01, 1.0)
        self.cb_size_h_spinbox.setValue(0.8)
        self.cb_size_h_spinbox.setSingleStep(0.01)
        self.cb_size_h_spinbox.setDecimals(2)
        size_layout_cb.addWidget(self.cb_size_h_spinbox)
        cb_layout.addLayout(size_layout_cb, 6, 1, 1, 2)
        layout.addWidget(general_group)
        layout.addWidget(key_group)
        layout.addWidget(cb_group)
        self.toggle_key_options()
        self.toggle_cb_size_controls()
        self.toggle_colorbar_options()
        return panel

    def create_preview_settings_panel(self):
        panel = QGroupBox("7. 高速プレビュー")
        layout = QGridLayout(panel)
        self.fast_preview_check = QCheckBox("プレビューのみ点数を減らす（推奨）")
        self.fast_preview_check.setChecked(True)
        layout.addWidget(self.fast_preview_check, 0, 0, 1, 2)
        layout.addWidget(QLabel("プレビューの最大点数 / データファイル:"), 1, 0)
        self.preview_max_points = QSpinBox()
        self.preview_max_points.setRange(1000, 1000000)
        self.preview_max_points.setSingleStep(5000)
        self.preview_max_points.setValue(20000)
        self.preview_max_points.setToolTip("100万点なら約2万点に間引いて描画。3D格子は行と走査線を間引きます。")
        layout.addWidget(self.preview_max_points, 1, 1)
        self.preview_notice = QLabel("PNG・PDF・SVG・GP・Cの出力は元の全点を使用します。")
        self.preview_notice.setWordWrap(True)
        layout.addWidget(self.preview_notice, 2, 0, 1, 2)
        return panel

    def connect_signals(self, *args, **kwargs):
        self.fast_preview_check.stateChanged.connect(
            lambda: self.preview_max_points.setEnabled(self.fast_preview_check.isChecked()))
        self.fast_preview_check.stateChanged.connect(self.request_redraw)
        self.preview_max_points.valueChanged.connect(self.request_redraw)
        self.plot_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.add_as_vector_check.stateChanged.connect(self.update_column_input_ui)
        self.add_as_model_check.stateChanged.connect(lambda state: self.add_as_vector_check.setEnabled(not state))
        self.add_as_model_check.stateChanged.connect(lambda state: self.add_as_vector_check.setChecked(False) if state else None)
        self.add_as_model_check.stateChanged.connect(self.update_column_input_ui)
        
        self.drop_zone.fileDropped.connect(self.handle_dropped_file)
        self.title_check.stateChanged.connect(lambda: self.title_input.setEnabled(self.title_check.isChecked()))
        self.title_check.stateChanged.connect(self.request_redraw)
        self.title_input.textChanged.connect(self.request_redraw)
        text_widgets = [self.xlabel_input, self.ylabel_input, self.y2label_input, self.zlabel_input,
                        self.xrange_min, self.xrange_max, self.yrange_min, self.yrange_max,
                        self.y2range_min, self.y2range_max, self.zrange_min, self.zrange_max,
                        self.xtics_xoffset, self.xtics_yoffset, self.ytics_xoffset, self.ytics_yoffset,
                        self.y2tics_xoffset, self.y2tics_yoffset, self.ztics_xoffset, self.ztics_yoffset,
                        self.width_input, self.height_input, self.cblabel_input, self.cbrange_min, self.cbrange_max,
                        self.xyplane_input] # xyplane_input added
        for widget in text_widgets:
            widget.textChanged.connect(self.request_redraw)
        combo_widgets = [self.key_pos_combo, self.font_combo]
        for widget in combo_widgets:
            widget.currentIndexChanged.connect(self.request_redraw)
        check_widgets = [self.xrange_check, self.yrange_check, self.y2range_check, self.zrange_check,
                         self.xtics_check, self.ytics_check, self.ztics_check, self.y2tics_offset_check,
                         self.logscale_x_check, self.logscale_y_check, self.logscale_y2_check, self.logscale_z_check,
                         self.grid_check, self.pm3d_check, self.cb_format_10_power_check]
        for widget in check_widgets:
            widget.stateChanged.connect(self.request_redraw)

        # 追加: 新しいSpinBoxのシグナル
        self.border_width_spinbox.valueChanged.connect(self.request_redraw)
        self.grid_width_spinbox.valueChanged.connect(self.request_redraw)
        self.grid_check.stateChanged.connect(lambda state: self.grid_width_spinbox.setEnabled(self.grid_check.isChecked()))
        self.grid_check.stateChanged.connect(lambda state: self.grid_width_label.setEnabled(self.grid_check.isChecked()))

        self.key_check.stateChanged.connect(self.toggle_key_options)
        self.key_check.stateChanged.connect(self.request_redraw)
        self.key_maxrows_spinbox.valueChanged.connect(self.request_redraw)
        self.key_maxcols_spinbox.valueChanged.connect(self.request_redraw)
        self.colorbar_check.stateChanged.connect(self.toggle_colorbar_options)
        self.colorbar_check.stateChanged.connect(self.request_redraw)
        self.cbrange_check.stateChanged.connect(self.request_redraw)
        self.cbsize_check.stateChanged.connect(self.toggle_cb_size_controls)
        self.cbsize_check.stateChanged.connect(self.request_redraw)
        spin_widgets = [self.cb_origin_x_spinbox, self.cb_origin_y_spinbox, self.cb_size_w_spinbox, self.cb_size_h_spinbox]
        for widget in spin_widgets:
            widget.valueChanged.connect(self.request_redraw)
        for slider, label in [(self.view_rot_x_slider, self.view_rot_x_label), (self.view_rot_z_slider, self.view_rot_z_label)]:
            slider.valueChanged.connect(lambda v, lbl=label: lbl.setText(str(v)))
            slider.valueChanged.connect(self.request_redraw)
        self.font_slider.valueChanged.connect(lambda v: self.font_label.setText(str(v)))
        self.font_slider.valueChanged.connect(self.request_redraw)
        self.plot_tabs.tabCloseRequested.connect(self.remove_plot)
        self.plot_tabs.tabBar().tabMoved.connect(self.handle_tab_moved)

        # xyplane logic
        self.xyplane_check.stateChanged.connect(lambda: self.xyplane_input.setEnabled(self.xyplane_check.isChecked()))
        self.xyplane_check.stateChanged.connect(self.request_redraw)

    def toggle_key_options(self, *args, **kwargs):
        is_enabled = self.key_check.isChecked()
        self.key_pos_combo.setEnabled(is_enabled)
        self.key_maxrows_spinbox.setEnabled(is_enabled)
        self.key_maxcols_spinbox.setEnabled(is_enabled)

    def toggle_colorbar_options(self, *args, **kwargs):
        is_enabled = self.colorbar_check.isChecked()
        for widget in [self.cblabel_input, self.cb_format_10_power_check, self.cbrange_check, self.cbrange_min, self.cbrange_max, self.cbsize_check]:
            widget.setEnabled(is_enabled)
        if is_enabled:
            self.toggle_cb_size_controls()
        else:
            [w.setEnabled(False) for w in [self.cb_origin_x_spinbox, self.cb_origin_y_spinbox, self.cb_size_w_spinbox, self.cb_size_h_spinbox]]

    def toggle_cb_size_controls(self, *args, **kwargs):
        is_custom = self.cbsize_check.isChecked() and self.colorbar_check.isChecked()
        for widget in [self.cb_origin_x_spinbox, self.cb_origin_y_spinbox, self.cb_size_w_spinbox, self.cb_size_h_spinbox]:
            widget.setEnabled(is_custom)

    def on_mode_changed(self, *args, **kwargs):
        if self.plots:
            reply = QMessageBox.question(self, 'Mode Change', "Changing plot mode will clear all plots. Continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                self.plot_mode_combo.blockSignals(True)
                self.plot_mode_combo.setCurrentIndex(0 if self.current_mode == '2d' else 1)
                self.plot_mode_combo.blockSignals(False)
                return
        self.clear_all_plots()
        is_3d = self.plot_mode_combo.currentIndex() == 1
        self.current_mode = "3d" if is_3d else "2d"
        self.target_axis_label.setVisible(not is_3d)
        self.new_plot_axis_combo.setVisible(not is_3d)
        self.axis_tabs.setTabVisible(self.axis_tabs.indexOf(self.y2_axis_tab), not is_3d)
        self.axis_tabs.setTabVisible(self.axis_tabs.indexOf(self.z_axis_tab), is_3d)
        self.view_settings_panel.setVisible(is_3d)
        self.update_column_input_ui()
        self.request_redraw()

    def update_column_input_ui(self, *args, **kwargs):
        while self.column_input_layout.count():
            child = self.column_input_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.column_spinboxes.clear()
        
        is_vector = self.add_as_vector_check.isChecked()
        is_model = self.add_as_model_check.isChecked()
        is_3d = (self.current_mode == '3d')
        
        if is_model:
            num_boxes = 3 if is_3d else 2
            labels = ["x", "y", "z"] if is_3d else ["x", "y"]
        else:
            num_boxes, labels = ((6, ["x", "y", "z", "dx", "dy", "dz"]) if is_vector else (3, ["x", "y", "z"])) if is_3d else ((4, ["x", "y", "dx", "dy"]) if is_vector else (2, ["x", "y"]))
        
        for i in range(num_boxes):
            spinbox = QSpinBox()
            spinbox.setMinimum(1)
            spinbox.setValue(i + 1)
            spinbox.setToolTip(labels[i])
            self.column_spinboxes.append(spinbox)
            self.column_input_layout.addWidget(spinbox)

    def handle_dropped_file(self, file_path):
        self.current_selected_file_path = file_path
        self.new_plot_file_input.setText(os.path.basename(file_path))

    def select_plot_file(self, *args, **kwargs):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Data File", "", "Data Files (*.dat *.txt);;All Files (*)")
        if file_name:
            self.current_selected_file_path = file_name
            self.new_plot_file_input.setText(os.path.basename(file_name))

    def request_redraw(self, *args, **kwargs):
        # 古いデータ準備と描画を即キャンセル。最後の操作の250ms後に再描画する。
        self._preview_generation += 1
        self._preview_cancel_event.set()
        self._cancel_preview_process()
        self.update_timer.start(250)

    def _cancel_preview_process(self):
        process = self._preview_process
        self._preview_process = None
        if process is not None and process.state() != QProcess.NotRunning:
            process.kill()

    def add_plot(self, *args, **kwargs):
        if not self.current_selected_file_path:
            QMessageBox.warning(self, "Warning", "Please select a file first.")
            return
        
        using = ":".join([str(sb.value()) for sb in self.column_spinboxes])
        is_vector = self.add_as_vector_check.isChecked()
        is_model = self.add_as_model_check.isChecked()

        plot_info = {
            "path": self.current_selected_file_path, "using": using, "is_vector": is_vector,
            "is_3d_mode": self.current_mode == '3d',
            "is_model_mode": is_model,
            "style": {
                "style": "lines", "color": "black", "linestyle": "Solid", "linewidth": 1.0,
                "pointtype": 1, "pointsize": 1.0, "color_from_value": False, "color_expression": "",
                "vector_options": {"nohead": False, "head_style": "Default", "head_size": "0.1,15,60", "length_scale": 1.0, "normalize": False}
            }
        }
        
        if is_model:
            plot_info["style"]["style"] = "lines"
            plot_info["style"]["color"] = "gray"
            plot_info["style"]["color_from_value"] = False
            plot_info["style"]["color_expression"] = ""
        elif is_vector:
            plot_info["style"]["color_from_value"] = True
            cols = [f"${c}" for c in plot_info["using"].split(':')]
            if self.current_mode == '2d':
                plot_info["style"]["color_expression"] = f"sqrt({cols[2]}**2+{cols[3]}**2)" if len(cols) > 3 else ""
            else:
                plot_info["style"]["color_expression"] = f"sqrt({cols[3]}**2+{cols[4]}**2+{cols[5]}**2)" if len(cols) > 5 else ""
        
        if self.current_mode == '2d':
            plot_info["axis"] = "y1" if self.new_plot_axis_combo.currentIndex() == 0 else "y2"
            plot_info["title"] = f"{os.path.basename(self.current_selected_file_path)} u {using} ({plot_info['axis']})"
        else:
            plot_info["axis"] = None
            plot_info["title"] = f"{os.path.basename(self.current_selected_file_path)} u {using}"
            if is_model:
                plot_info["title"] += " (Model)"
        
        self.plots.append(plot_info)
        editor = PlotEditorWidget(plot_info, self.dashtype_map)
        editor.plotChanged.connect(self.request_redraw)
        editor.titleChanged.connect(lambda title, idx=len(self.plots)-1: self.plot_tabs.setTabText(idx, title))
        tab_index = self.plot_tabs.addTab(editor, plot_info["title"])
        self.plot_tabs.setCurrentIndex(tab_index)
        self.new_plot_file_input.clear()
        self.current_selected_file_path = None
        self.request_redraw()

    def remove_plot(self, index):
        reply = QMessageBox.question(self, 'Remove Plot', f"Are you sure you want to remove the plot '{self.plots[index]['title']}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.plot_tabs.removeTab(index)
            self.plots.pop(index)
            for i in range(self.plot_tabs.count()):
                editor = self.plot_tabs.widget(i)
                try:
                    editor.titleChanged.disconnect()
                except RuntimeError:
                    pass
                editor.titleChanged.connect(lambda title, idx=i: self.plot_tabs.setTabText(idx, title))
            self.request_redraw()

    def handle_tab_moved(self, from_index, to_index):
        moved_plot = self.plots.pop(from_index)
        self.plots.insert(to_index, moved_plot)
        for i in range(self.plot_tabs.count()):
            editor = self.plot_tabs.widget(i)
            try:
                editor.titleChanged.disconnect()
            except RuntimeError:
                pass
            editor.titleChanged.connect(lambda title, idx=i: self.plot_tabs.setTabText(idx, title))
        self.request_redraw()

    def generate_gnuplot_script(self, output_path=None, terminal_cmd=None, preview_paths=None):
        if not self.plots: return None
        if terminal_cmd: script = f"{terminal_cmd}\n"
        else:
            font_setting = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
            width = int(self.width_input.text() or "800")
            height = int(self.height_input.text() or "600")
            script = f'set terminal pngcairo size {width},{height} enhanced {font_setting}\n'
        if output_path: script += f'set output "{output_path}"\n'
        script += 'set encoding utf8\n'
        script += 'set palette rgbformulae 22,13,-31\n'
        
        # 追加: 枠線・目盛りの太さ設定
        script += f'set border linewidth {self.border_width_spinbox.value():.1f}\n'

        if self.title_check.isChecked() and self.title_input.text(): script += f'set title "{self.title_input.text()}"\n'
        if self.xlabel_input.text(): script += f'set xlabel "{self.xlabel_input.text()}"\n'
        if self.ylabel_input.text(): script += f'set ylabel "{self.ylabel_input.text()}"\n'
        if self.xrange_check.isChecked() and self.xrange_min.text() and self.xrange_max.text(): script += f'set xrange [{self.xrange_min.text()}:{self.xrange_max.text()}]\n'
        if self.yrange_check.isChecked() and self.yrange_min.text() and self.yrange_max.text(): script += f'set yrange [{self.yrange_min.text()}:{self.yrange_max.text()}]\n'
        
        if self.colorbar_check.isChecked():
            if self.cbsize_check.isChecked():
                script += f'set colorbox user origin {self.cb_origin_x_spinbox.value():.2f},{self.cb_origin_y_spinbox.value():.2f} size {self.cb_size_w_spinbox.value():.2f},{self.cb_size_h_spinbox.value():.2f}\n'
            else: script += 'set colorbox default\n'
            if self.cblabel_input.text(): script += f'set cblabel "{self.cblabel_input.text()}"\n'
            if self.cbrange_check.isChecked() and self.cbrange_min.text() and self.cbrange_max.text(): script += f'set cbrange [{self.cbrange_min.text()}:{self.cbrange_max.text()}]\n'
            
            if self.cb_format_10_power_check.isChecked():
                script += 'set format cb "%.1tx10^{%T}"\n'
            else:
                script += 'unset format cb\n'
        else: script += 'unset colorbox\n'

        log_axes = ""
        if self.logscale_x_check.isChecked(): log_axes += "x"
        if self.logscale_y_check.isChecked(): log_axes += "y"
        
        # 追加: グリッド設定と太さ
        if self.grid_check.isChecked(): 
            script += f'set grid linewidth {self.grid_width_spinbox.value():.1f}\n'
        
        if self.key_check.isChecked():
            key_options = [self.key_pos_combo.currentText()]
            maxrows = self.key_maxrows_spinbox.value()
            if maxrows > 0: key_options.append(f"maxrows {maxrows}")
            maxcols = self.key_maxcols_spinbox.value()
            if maxcols > 0: key_options.append(f"maxcols {maxcols}")
            script += f'set key {" ".join(key_options)}\n'
        else:
            script += 'set key off\n'

        if self.xtics_check.isChecked(): script += f'set xtics offset {self.xtics_xoffset.text() or "0"},{self.xtics_yoffset.text() or "0"}\n'
        if self.ytics_check.isChecked(): script += f'set ytics offset {self.ytics_xoffset.text() or "0"},{self.ytics_yoffset.text() or "0"}\n'

        if self.current_mode == '2d':
            has_y2 = any(p.get('axis') == 'y2' for p in self.plots)
            if has_y2 and self.y2label_input.text(): script += f'set y2label "{self.y2label_input.text()}"\n'
            if has_y2 and self.y2range_check.isChecked() and self.y2range_min.text() and self.y2range_max.text(): script += f'set y2range [{self.y2range_min.text()}:{self.y2range_max.text()}]\n'
            if has_y2:
                script += 'set ytics nomirror\nset y2tics\n'
                if self.y2tics_offset_check.isChecked(): script += f'set y2tics offset {self.y2tics_xoffset.text() or "0"},{self.y2tics_yoffset.text() or "0"}\n'
            if has_y2 and self.logscale_y2_check.isChecked(): log_axes += "y2"
            plot_command = "plot"
        else: # 3d
            if self.zlabel_input.text(): script += f'set zlabel "{self.zlabel_input.text()}" rotate by 90\n'
            if self.zrange_check.isChecked() and self.zrange_min.text() and self.zrange_max.text(): script += f'set zrange [{self.zrange_min.text()}:{self.zrange_max.text()}]\n'
            if self.ztics_check.isChecked(): script += f'set ztics offset {self.ztics_xoffset.text() or "0"},{self.ztics_yoffset.text() or "0"}\n'
            if self.logscale_z_check.isChecked(): log_axes += "z"
            script += f'set view {self.view_rot_x_slider.value()},{self.view_rot_z_slider.value()}\n'
            if self.pm3d_check.isChecked(): script += 'set pm3d explicit\n'
            else: script += 'unset pm3d\n'
            
            # --- xyplane setting ---
            if self.xyplane_check.isChecked():
                script += f'set xyplane at {self.xyplane_input.text()}\n'
            # -----------------------

            plot_command = "splot"

        if log_axes: script += f'set logscale {log_axes}\n'
        else: script += 'unset logscale\n'

        normal_parts = []
        model_parts = []
        
        for plot_info in self.plots:
            style_info = plot_info["style"]
            is_vector = plot_info.get("is_vector", False)
            is_model = plot_info.get("is_model_mode", False)
            
            if is_model:
                orig_cols = plot_info['using'].split(':')
                limit = 3 if self.current_mode == '3d' else 2
                using_cols = [f"(${c})" for c in orig_cols[:limit]]
            else:
                cols = plot_info['using'].split(':')
                using_cols = [f"(${c})" for c in cols]

            if is_vector and not is_model:
                vec_opts = style_info.get("vector_options", {})
                if vec_opts.get("normalize", False):
                    magnitude_expr = style_info.get("color_expression")
                    if magnitude_expr:
                        magnitude_safe = f"(({magnitude_expr}) == 0 ? 1 : ({magnitude_expr}))"
                        if self.current_mode == '2d' and len(using_cols) >= 4: using_cols[2] = f"({using_cols[2]} / {magnitude_safe})"; using_cols[3] = f"({using_cols[3]} / {magnitude_safe})"
                        elif self.current_mode == '3d' and len(using_cols) >= 6: using_cols[3] = f"({using_cols[3]} / {magnitude_safe})"; using_cols[4] = f"({using_cols[4]} / {magnitude_safe})"; using_cols[5] = f"({using_cols[5]} / {magnitude_safe})"
                scale = vec_opts.get('length_scale', 1.0)
                if scale != 1.0:
                    if self.current_mode == '2d' and len(using_cols) >= 4: using_cols[2] = f"({using_cols[2]} * {scale})"; using_cols[3] = f"({using_cols[3]} * {scale})"
                    elif self.current_mode == '3d' and len(using_cols) >= 6: using_cols[3] = f"({using_cols[3]} * {scale})"; using_cols[4] = f"({using_cols[4]} * {scale})"; using_cols[5] = f"({using_cols[5]} * {scale})"
            
            if style_info.get("color_from_value", False) and style_info.get("color_expression", "") and not is_model:
                using_cols.append(f'({style_info["color_expression"]})')
            
            using_str = "using " + ":".join(using_cols)
            style_details = ""
            
            if is_vector and not is_model:
                style_details = "with vectors"
                vec_opts = style_info.get("vector_options", {})
                if vec_opts.get("nohead"): style_details += " nohead"
                else:
                    if vec_opts.get("head_style", "Default") != "Default": style_details += f' head {vec_opts["head_style"].lower()}'
                    if vec_opts.get("head_size", "").strip(): style_details += f' size {vec_opts["head_size"]}'
                dt_val = self.dashtype_map.get(style_info['linestyle'], 1)
                style_details += f" dashtype {dt_val} linewidth {style_info['linewidth']}"
            else:
                style = style_info["style"]
                style_details = "with pm3d" if style == 'pm3d' else f"with {style}"
                if "lines" in style or style in ["impulses", "steps"]:
                    dt_val = self.dashtype_map.get(style_info['linestyle'], 1); style_details += f" dashtype {dt_val} linewidth {style_info['linewidth']}"
                if "points" in style or style in ["dots"]: style_details += f" pointtype {style_info['pointtype']} pointsize {style_info['pointsize']}"
            
            if style_info.get("color_from_value") and not is_model:
                style_details += " lc palette"
            else:
                style_details += f' linecolor rgb "{style_info["color"]}"'
            
            # 間引きデータに差し替えるのはプレビュー時だけ。通常のGP/画像出力は元ファイル。
            plot_path = preview_paths.get(plot_info["path"], plot_info["path"]) if preview_paths else plot_info["path"]
            plot_path = plot_path.replace('\\', '/')
            path_str = f'"{plot_path}" {using_str}'; title_str = f'title "{plot_info["title"]}"' 
            
            part_str = ""
            if self.current_mode == '2d':
                axis_cmd = "x1y1" if plot_info.get("axis") == "y1" else "x1y2"
                part_str = f'{path_str} axes {axis_cmd} {style_details} {title_str}'
            else:
                part_str = f'{path_str} {style_details} {title_str}'
            
            if is_model:
                model_parts.append(part_str)
            else:
                normal_parts.append(part_str)

        if model_parts:
            script += "set multiplot\n"
            
            # --- 余白調整（Fix for margins sticking out）---
            # 2D/3Dモードに応じて適切な余白を設定します。
            # 目盛りやラベルの大きさを考慮し、以前よりも余裕を持たせた値を設定しました。
            if self.current_mode == '2d':
                # 2Dの場合、左側にY軸ラベル、下側にX軸ラベルのスペースを確保
                script += "set lmargin screen 0.20\nset rmargin screen 0.85\nset bmargin screen 0.20\nset tmargin screen 0.90\n"
            else:
                # 3Dの場合、回転によって軸が大きくはみ出す可能性があるため、さらに余裕を確保
                script += "set lmargin screen 0.20\nset rmargin screen 0.80\nset bmargin screen 0.30\nset tmargin screen 0.90\n"
            # -----------------------------------------------

            if normal_parts:
                script += f"{plot_command} " + ", \\\n    ".join(normal_parts) + "\n"
                
                # --- 範囲の完全固定処理 ---
                script += "# Fix ranges and disable autoscale for the second plot\n"
                script += "set xrange [GPVAL_X_MIN:GPVAL_X_MAX]\n"
                script += "set yrange [GPVAL_Y_MIN:GPVAL_Y_MAX]\n"
                if self.current_mode == '3d':
                    script += "set zrange [GPVAL_Z_MIN:GPVAL_Z_MAX]\n"
                if self.current_mode == '2d' and any(p.get('axis') == 'y2' for p in self.plots):
                     script += "set y2range [GPVAL_Y2_MIN:GPVAL_Y2_MAX]\n"
                
                script += "unset autoscale\n" 
                # -------------------------
            
            script += "unset colorbox\n"
            script += "unset border\nunset key\n"

            script += f"{plot_command} " + ", \\\n    ".join(model_parts) + "\n"
            
            script += "unset multiplot\n"
            script += "set autoscale\n" 
        else:
            if normal_parts:
                script += f"{plot_command} " + ", \\\n    ".join(normal_parts) + "\n"

        return script

    def redraw_plot(self, *args, **kwargs):
        token = self._preview_generation
        # Command Preview には常に元データを用いた完全なスクリプトを表示する。
        try:
            script = self.generate_gnuplot_script()
        except Exception as exc:
            self.preview_status.setText(f"設定エラー: {exc}")
            return
        if not script:
            self._last_preview_pixmap = QPixmap()
            self.plot_label.setPixmap(QPixmap())
            self.plot_label.setText("Please add a plot to begin.")
            self.preview_status.clear()
            self.script_display.clear()
            self.script_display.setFixedHeight(30)
            return
        self.script_display.setText(script)
        new_height = int(self.script_display.document().size().height()) + 15
        self.script_display.setFixedHeight(new_height)

        if not self.fast_preview_check.isChecked():
            self.preview_status.setText("全点を使って描画中（設定変更は引き続き可能です）...")
            self._start_preview_process(token, script)
            return

        # 元データを編集せず、一度だけ作った間引きデータをキャッシュして再利用する。
        self.preview_status.setText("プレビュー用データを準備中...")
        self._preview_cancel_event = threading.Event()
        filenames = list(dict.fromkeys(p['path'] for p in self.plots))
        task = PreviewDataTask(
            self._preview_cache, filenames, self.preview_max_points.value(),
            self.current_mode == '3d', token, self._preview_cancel_event
        )
        task.signals.finished.connect(self._preview_data_ready)
        self._preview_pool.start(task)

    def _preview_data_ready(self, token, replacements, error):
        if token != self._preview_generation:
            return
        if error:
            self.preview_status.setText(f"プレビュー用データの準備に失敗: {error}")
            return
        try:
            script = self.generate_gnuplot_script(preview_paths=replacements)
        except Exception as exc:
            self.preview_status.setText(f"設定エラー: {exc}")
            return
        self.preview_status.setText("高速プレビューを描画中...")
        self._start_preview_process(token, script)

    def _start_preview_process(self, token, script):
        if token != self._preview_generation:
            return
        # QProcess は非同期。100万点でもプロセスの終了待ちでGUIが止まらない。
        process = QProcess(self)
        self._preview_process = process
        output = bytearray()
        errors = bytearray()

        def read_output():
            output.extend(bytes(process.readAllStandardOutput()))

        def read_error():
            errors.extend(bytes(process.readAllStandardError()))

        def send_script():
            process.write(script.encode('utf-8'))
            process.closeWriteChannel()

        def finished(exit_code, exit_status):
            read_output()
            read_error()
            if self._preview_process is process:
                self._preview_process = None
            if token == self._preview_generation:
                if exit_status != QProcess.NormalExit or exit_code != 0:
                    message = errors.decode('utf-8', 'replace').strip() or f"exit code: {exit_code}"
                    self.preview_status.setText(f"Gnuplot Error: {message[:1000]}")
                else:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(bytes(output)):
                        self._last_preview_pixmap = pixmap
                        self._show_last_preview()
                        self.preview_status.setText(
                            f"高速プレビュー（最大{self.preview_max_points.value():,}点/ファイル）"
                            if self.fast_preview_check.isChecked() else "全点プレビュー")
                    else:
                        message = errors.decode('utf-8', 'replace').strip()
                        self.preview_status.setText(
                            f"Gnuplotの画像を読み込めませんでした。{message[:500]}")
            process.deleteLater()

        def failed(error):
            if error == QProcess.FailedToStart:
                if self._preview_process is process:
                    self._preview_process = None
                if token == self._preview_generation:
                    self.preview_status.setText("Gnuplotを起動できません。PATHとインストールを確認してください。")
                process.deleteLater()

        process.readyReadStandardOutput.connect(read_output)
        process.readyReadStandardError.connect(read_error)
        process.started.connect(send_script)
        process.finished.connect(finished)
        process.errorOccurred.connect(failed)
        process.start('gnuplot')

    def _show_last_preview(self):
        if not self._last_preview_pixmap.isNull():
            size = self.plot_label.size()
            if size.width() > 0 and size.height() > 0:
                scaled = self._last_preview_pixmap.scaled(
                    size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.plot_label.setPixmap(scaled)

    def save_image(self, *args, **kwargs):
        if not self.plots:
            QMessageBox.warning(self, "Error", "No data to plot.")
            return
        file_name, selected_filter = QFileDialog.getSaveFileName(self, "Save Graph As", "", "PNG Image (*.png);;SVG Image (*.svg);;PDF Document (*.pdf)")
        if not file_name:
            return
        width, height = int(self.width_input.text() or "800"), int(self.height_input.text() or "600")
        font = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
        if "svg" in selected_filter:
            term_cmd = f'set terminal svg size {width},{height} {font}'
        elif "pdf" in selected_filter:
            term_cmd = f'set terminal pdfcairo size {width/100.0:.2f},{height/100.0:.2f} {font}'
        else:
            term_cmd = f'set terminal pngcairo size {width},{height} enhanced {font}'
        script = self.generate_gnuplot_script(output_path=file_name, terminal_cmd=term_cmd)
        if not script:
            QMessageBox.critical(self, "Error", "Failed to generate script.")
            return
        try:
            process = subprocess.Popen(['gnuplot'], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=CREATE_NO_WINDOW)
            _, stderr = process.communicate(script)
            if process.returncode == 0:
                QMessageBox.information(self, "Success", f"Graph saved to {file_name}")
            else:
                QMessageBox.critical(self, "Gnuplot Error", f"Failed to save graph.\n\n{stderr}")
        except Exception as e:
            QMessageBox.critical(self, "Runtime Error", f"An error occurred.\n\n{e}")

    def save_gp_file(self, *args, **kwargs):
        if not self.plots:
            QMessageBox.warning(self, "Warning", "No plot data to save.")
            return
        base_script = self.generate_gnuplot_script()
        if not base_script:
            QMessageBox.critical(self, "Error", "Failed to generate script.")
            return
        script_lines = base_script.splitlines()
        font_setting = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
        interactive_terminal = f'set terminal wxt enhanced {font_setting}'
        for i, line in enumerate(script_lines):
            if line.strip().startswith("set terminal pngcairo"):
                script_lines[i] = interactive_terminal
                break
        else:
            script_lines.insert(0, interactive_terminal)
        script_lines.append('\npause -1 "Press Enter or close window to exit."')
        script_content = "\n".join(script_lines)
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Gnuplot Script As", "", "Gnuplot Script (*.gp);;All Files (*)")
        if not file_name:
            return
        try:
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write(script_content)
            QMessageBox.information(self, "Success", f"Script saved to {os.path.basename(file_name)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save script file.\n\n{e}")

    def save_for_c(self):
        if not self.plots:
            QMessageBox.warning(self, "Warning", "No plot data to save.")
            return

        file_name, _ = QFileDialog.getSaveFileName(self, "Save for C Language As", "", "C Source File (*.c);;All Files (*)")
        if not file_name:
            return

        output_dir_name = "output"
        output_png_basename = os.path.splitext(os.path.basename(file_name))[0] + ".png"
        gnuplot_output_path = f"{output_dir_name}/{output_png_basename}"

        width = int(self.width_input.text() or "800")
        height = int(self.height_input.text() or "600")
        font = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
        term_cmd = f'set terminal pngcairo size {width},{height} enhanced {font}'
        
        script_content = self.generate_gnuplot_script(output_path=gnuplot_output_path, terminal_cmd=term_cmd)

        if not script_content:
            QMessageBox.critical(self, "Error", "Failed to generate script.")
            return

        c_code_parts = [
            '#include <stdio.h>', '#include <stdlib.h>',
            '#ifdef _WIN32', '#include <direct.h>', '#define MKDIR(path) _mkdir(path)',
            '#else', '#include <sys/stat.h>', '#include <sys/types.h>', '#define MKDIR(path) mkdir(path, 0777)', '#endif',
            '',
            'int main() {', '    FILE *gp;', f'    const char* dir_name = "{output_dir_name}";',
            '', '    MKDIR(dir_name);', '', '    gp = popen("gnuplot", "w");',
            '    if (gp == NULL) {',
            '        fprintf(stderr, "Error: gnuplotが見つかりません。PATHを確認してください。\\n");',
            '        return 1;', '    }', '', '    // Gnuplotコマンドの送信',
        ]

        for line in script_content.splitlines():
            escaped_line = line.replace('\\', '\\\\').replace('"', '\\"')
            c_code_parts.append(f'    fprintf(gp, "{escaped_line}\\n");')
             
        c_code_parts.extend([
            '', '    pclose(gp);', '',
            f'    printf("Graph saved to {gnuplot_output_path.replace("\\\\", "/")}\\n");',
            '', '    return 0;', '}'
        ])
        
        c_content = "\n".join(c_code_parts)

        try:
            with open(file_name, 'w', encoding='utf-8') as f: f.write(c_content)
            QMessageBox.information(self, "Success", f"C source file saved to {os.path.basename(file_name)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save C source file.\n\n{e}")

    def export_project(self):
        """現在の設定からPNG, GP, Cファイルを一括でフォルダに保存する"""
        if not self.plots:
            QMessageBox.warning(self, "Warning", "No plot data to export.")
            return
            
        base_dir = QFileDialog.getExistingDirectory(self, "Select Directory to Save Project Folder")
        if not base_dir:
            return

        project_name, ok = QInputDialog.getText(self, "Export Project", "Enter a project name (for folder and files):", text="my_plot_project")
        if not ok or not project_name:
            return

        project_path = os.path.join(base_dir, project_name)
        
        try:
            os.makedirs(project_path, exist_ok=True)
            
            # --- 1. PNGを保存 ---
            png_path = os.path.join(project_path, project_name + ".png").replace('\\', '/')
            width, height = int(self.width_input.text() or "800"), int(self.height_input.text() or "600")
            font = f'font "{self.font_combo.currentText()},{self.font_slider.value()}"'
            term_cmd = f'set terminal pngcairo size {width},{height} enhanced {font}'
            script = self.generate_gnuplot_script(output_path=png_path, terminal_cmd=term_cmd)
            process = subprocess.Popen(['gnuplot'], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=CREATE_NO_WINDOW)
            _, stderr = process.communicate(script)
            if process.returncode != 0: raise Exception(f"Gnuplot error for PNG:\n{stderr}")

            # --- 2. GPファイルを保存 ---
            gp_path = os.path.join(project_path, project_name + ".gp")
            base_script_gp = self.generate_gnuplot_script()
            script_lines_gp = base_script_gp.splitlines()
            interactive_terminal = f'set terminal wxt enhanced {font}'
            for i, line in enumerate(script_lines_gp):
                if line.strip().startswith("set terminal pngcairo"):
                    script_lines_gp[i] = interactive_terminal
                    break
            else: script_lines_gp.insert(0, interactive_terminal)
            script_lines_gp.append('\npause -1 "Press Enter or close window to exit."')
            with open(gp_path, 'w', encoding='utf-8') as f: f.write("\n".join(script_lines_gp))

            # --- 3. Cファイルを保存 ---
            c_path = os.path.join(project_path, project_name + ".c")
            output_dir_name = "output"
            gnuplot_output_path = f"{output_dir_name}/{project_name}.png"
            script_content_c = self.generate_gnuplot_script(output_path=gnuplot_output_path, terminal_cmd=term_cmd)
            
            c_code_parts = [
                '#include <stdio.h>', '#include <stdlib.h>',
                '#ifdef _WIN32', '#include <direct.h>', '#define MKDIR(path) _mkdir(path)',
                '#else', '#include <sys/stat.h>', '#include <sys/types.h>', '#define MKDIR(path) mkdir(path, 0777)', '#endif',
                '', 'int main() {', '    FILE *gp;', f'    const char* dir_name = "{output_dir_name}";',
                '', '    MKDIR(dir_name);', '', '    gp = popen("gnuplot", "w");',
                '    if (gp == NULL) {', '        fprintf(stderr, "Error: gnuplotが見つかりません。PATHを確認してください。\\n");', '        return 1;', '    }', '', '    // Gnuplotコマンドの送信',
            ]
            for line in script_content_c.splitlines():
                escaped_line = line.replace('\\', '\\\\').replace('"', '\\"')
                c_code_parts.append(f'    fprintf(gp, "{escaped_line}\\n");')
            c_code_parts.extend([
                '', '    pclose(gp);', '', f'    printf("Graph saved to {gnuplot_output_path.replace("\\\\", "/")}\\n");', '', '    return 0;', '}'
            ])
            with open(c_path, 'w', encoding='utf-8') as f: f.write("\n".join(c_code_parts))
            
            QMessageBox.information(self, "Export Successful", f"Project '{project_name}' was successfully exported to:\n{base_dir}")

        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"An error occurred during export.\n\n{e}")

    def collect_settings(self, *args, **kwargs):
        settings = {
            'version': 3.1, # bumped version
            'plot_mode': self.plot_mode_combo.currentIndex(), 'plots': self.plots,
            'legend': {'key_check': self.key_check.isChecked(), 'key_pos': self.key_pos_combo.currentText(), 'key_maxrows': self.key_maxrows_spinbox.value(), 'key_maxcols': self.key_maxcols_spinbox.value()},
            'general': {'title_check': self.title_check.isChecked(), 'title_input': self.title_input.text(), 'border_width': self.border_width_spinbox.value()},
            'xaxis': {'label': self.xlabel_input.text(), 'range_check': self.xrange_check.isChecked(), 'range_min': self.xrange_min.text(), 'range_max': self.xrange_max.text(), 'tics_check': self.xtics_check.isChecked(), 'tics_xoffset': self.xtics_xoffset.text(), 'tics_yoffset': self.xtics_yoffset.text(), 'log_check': self.logscale_x_check.isChecked(), 'grid_check': self.grid_check.isChecked(), 'grid_width': self.grid_width_spinbox.value()},
            'yaxis': {'label': self.ylabel_input.text(), 'range_check': self.yrange_check.isChecked(), 'range_min': self.yrange_min.text(), 'range_max': self.yrange_max.text(), 'tics_check': self.ytics_check.isChecked(), 'tics_xoffset': self.ytics_xoffset.text(), 'tics_yoffset': self.ytics_yoffset.text(), 'log_check': self.logscale_y_check.isChecked()},
            'y2axis': {'label': self.y2label_input.text(), 'range_check': self.y2range_check.isChecked(), 'range_min': self.y2range_min.text(), 'range_max': self.y2range_max.text(), 'tics_check': self.y2tics_offset_check.isChecked(), 'tics_xoffset': self.y2tics_xoffset.text(), 'tics_yoffset': self.y2tics_yoffset.text(), 'log_check': self.logscale_y2_check.isChecked()},
            'zaxis': {'label': self.zlabel_input.text(), 'range_check': self.zrange_check.isChecked(), 'range_min': self.zrange_min.text(), 'range_max': self.zrange_max.text(), 'tics_check': self.ztics_check.isChecked(), 'tics_xoffset': self.ztics_xoffset.text(), 'tics_yoffset': self.ztics_yoffset.text(), 'log_check': self.logscale_z_check.isChecked()},
            'view3d': {'rot_x': self.view_rot_x_slider.value(), 'rot_z': self.view_rot_z_slider.value(), 'pm3d_check': self.pm3d_check.isChecked(), 'xyplane_check': self.xyplane_check.isChecked(), 'xyplane_value': self.xyplane_input.text()}, # Added xyplane
            'output': {'width': self.width_input.text(), 'height': self.height_input.text(), 'font_name': self.font_combo.currentText(), 'font_size': self.font_slider.value()},
            'preview': {'fast': self.fast_preview_check.isChecked(), 'max_points': self.preview_max_points.value()},
            'colorbar': {'check': self.colorbar_check.isChecked(), 'label': self.cblabel_input.text(), 'format_10_power': self.cb_format_10_power_check.isChecked(), 'range_check': self.cbrange_check.isChecked(), 'range_min': self.cbrange_min.text(), 'range_max': self.cbrange_max.text(), 'size_check': self.cbsize_check.isChecked(), 'origin_x': self.cb_origin_x_spinbox.value(), 'origin_y': self.cb_origin_y_spinbox.value(), 'size_w': self.cb_size_w_spinbox.value(), 'size_h': self.cb_size_h_spinbox.value()}
        }
        return settings

    def apply_settings(self, settings):
        self.clear_all_plots()
        all_widgets = self.findChildren(QWidget)
        for widget in all_widgets: widget.blockSignals(True)
        try:
            self.plot_mode_combo.setCurrentIndex(settings.get('plot_mode', 0))
            is_3d = self.plot_mode_combo.currentIndex() == 1
            self.current_mode = "3d" if is_3d else "2d"
            self.target_axis_label.setVisible(not is_3d); self.new_plot_axis_combo.setVisible(not is_3d)
            self.axis_tabs.setTabVisible(self.axis_tabs.indexOf(self.y2_axis_tab), not is_3d)
            self.axis_tabs.setTabVisible(self.axis_tabs.indexOf(self.z_axis_tab), is_3d)
            self.view_settings_panel.setVisible(is_3d)
            self.update_column_input_ui()
            s = settings.get('legend', {}); self.key_check.setChecked(s.get('key_check', True)); self.key_pos_combo.setCurrentText(s.get('key_pos', 'default')); self.key_maxrows_spinbox.setValue(s.get('key_maxrows', 0)); self.key_maxcols_spinbox.setValue(s.get('key_maxcols', 0)); self.toggle_key_options()
            s = settings.get('general', {}); self.title_check.setChecked(s.get('title_check', False)); self.title_input.setText(s.get('title_input', '')); self.title_input.setEnabled(self.title_check.isChecked()); self.border_width_spinbox.setValue(s.get('border_width', 1.0))
            s = settings.get('xaxis', {}); self.xlabel_input.setText(s.get('label', 'X-Axis')); self.xrange_check.setChecked(s.get('range_check', False)); self.xrange_min.setText(s.get('range_min', '')); self.xrange_max.setText(s.get('range_max', '')); self.xtics_check.setChecked(s.get('tics_check', False)); self.xtics_xoffset.setText(s.get('tics_xoffset', '0')); self.xtics_yoffset.setText(s.get('tics_yoffset', '-1')); self.logscale_x_check.setChecked(s.get('log_check', False)); self.grid_check.setChecked(s.get('grid_check', False)); self.grid_width_spinbox.setValue(s.get('grid_width', 1.0)); self.grid_width_spinbox.setEnabled(self.grid_check.isChecked()); self.grid_width_label.setEnabled(self.grid_check.isChecked())
            s = settings.get('yaxis', {}); self.ylabel_input.setText(s.get('label', 'Y-Axis')); self.yrange_check.setChecked(s.get('range_check', False)); self.yrange_min.setText(s.get('range_min', '')); self.yrange_max.setText(s.get('range_max', '')); self.ytics_check.setChecked(s.get('tics_check', False)); self.ytics_xoffset.setText(s.get('tics_xoffset', '-1')); self.ytics_yoffset.setText(s.get('tics_yoffset', '0')); self.logscale_y_check.setChecked(s.get('log_check', False))
            s = settings.get('y2axis', {}); self.y2label_input.setText(s.get('label', 'Y2-Axis')); self.y2range_check.setChecked(s.get('range_check', False)); self.y2range_min.setText(s.get('range_min', '')); self.y2range_max.setText(s.get('range_max', '')); self.y2tics_offset_check.setChecked(s.get('tics_check', False)); self.y2tics_xoffset.setText(s.get('tics_xoffset', '1')); self.y2tics_yoffset.setText(s.get('tics_yoffset', '0')); self.logscale_y2_check.setChecked(s.get('log_check', False))
            s = settings.get('zaxis', {}); self.zlabel_input.setText(s.get('label', 'Z-Axis')); self.zrange_check.setChecked(s.get('range_check', False)); self.zrange_min.setText(s.get('range_min', '')); self.zrange_max.setText(s.get('range_max', '')); self.ztics_check.setChecked(s.get('tics_check', False)); self.ztics_xoffset.setText(s.get('tics_xoffset', '0')); self.ztics_yoffset.setText(s.get('tics_yoffset', '0')); self.logscale_z_check.setChecked(s.get('log_check', False))
            s = settings.get('view3d', {}); self.view_rot_x_slider.setValue(s.get('rot_x', 60)); self.view_rot_z_slider.setValue(s.get('rot_z', 30)); self.pm3d_check.setChecked(s.get('pm3d_check', True)); self.xyplane_check.setChecked(s.get('xyplane_check', False)); self.xyplane_input.setText(s.get('xyplane_value', '0')); self.xyplane_input.setEnabled(self.xyplane_check.isChecked()) # Added xyplane
            s = settings.get('output', {}); self.width_input.setText(s.get('width', '800')); self.height_input.setText(s.get('height', '600')); self.font_combo.setCurrentText(s.get('font_name', 'Times New Roman')); self.font_slider.setValue(s.get('font_size', 14))
            s = settings.get('preview', {}); self.fast_preview_check.setChecked(s.get('fast', True)); self.preview_max_points.setValue(s.get('max_points', 20000)); self.preview_max_points.setEnabled(self.fast_preview_check.isChecked())
            s = settings.get('colorbar', {}); self.colorbar_check.setChecked(s.get('check', True)); self.cblabel_input.setText(s.get('label', 'Magnitude')); self.cb_format_10_power_check.setChecked(s.get('format_10_power', False)); self.cbrange_check.setChecked(s.get('range_check', False)); self.cbrange_min.setText(s.get('range_min', '')); self.cbrange_max.setText(s.get('range_max', '')); self.cbsize_check.setChecked(s.get('size_check', False)); self.cb_origin_x_spinbox.setValue(s.get('origin_x', 0.92)); self.cb_origin_y_spinbox.setValue(s.get('origin_y', 0.1)); self.cb_size_w_spinbox.setValue(s.get('size_w', 0.04)); self.cb_size_h_spinbox.setValue(s.get('size_h', 0.8)); self.toggle_colorbar_options()
            loaded_plots = settings.get('plots', [])
            for i, plot_info in enumerate(loaded_plots):
                self.plots.append(plot_info)
                editor = PlotEditorWidget(plot_info, self.dashtype_map)
                editor.plotChanged.connect(self.request_redraw)
                editor.titleChanged.connect(lambda title, idx=i: self.plot_tabs.setTabText(idx, title))
                self.plot_tabs.addTab(editor, plot_info["title"])
        finally:
            for widget in self.findChildren(QWidget): widget.blockSignals(False)
        self.request_redraw()

    def save_settings(self, *args, **kwargs):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Settings As", "", "JSON Files (*.json)")
        if not file_name: return
        settings = self.collect_settings()
        try:
            with open(file_name, 'w', encoding='utf-8') as f: json.dump(settings, f, indent=4)
            QMessageBox.information(self, "Success", f"Settings saved to {os.path.basename(file_name)}")
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to save settings file.\n\n{e}")

    def load_settings(self, *args, **kwargs):
        if self.plots:
            reply = QMessageBox.question(self, 'Load Settings', "This will clear current plots and load new settings. Continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: return
        file_name, _ = QFileDialog.getOpenFileName(self, "Load Settings File", "", "JSON Files (*.json)")
        if not file_name: return
        try:
            with open(file_name, 'r', encoding='utf-8') as f: settings = json.load(f)
            self.apply_settings(settings)
            QMessageBox.information(self, "Success", f"Settings loaded from {os.path.basename(file_name)}")
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to load settings file.\n\n{e}")

    def auto_load_settings(self):
        """起動時に同ディレクトリの settings.json を自動で読み込む"""
        # __compiled__ は Nuitka コンパイル時に定義されるグローバル変数です
        if getattr(sys, 'frozen', False) or "__compiled__" in globals():
            # exe化されている場合
            # sys.executable ではなく、元のパスを保持している sys.argv[0] を使用する
            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        else:
            # 通常のPythonスクリプトとして実行されている場合
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        settings_path = os.path.join(base_dir, "settings.json")
        
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                self.apply_settings(settings)
            except Exception as e:
                print(f"Failed to auto-load settings: {e}")

    def clear_all_plots(self, *args, **kwargs):
        self._preview_generation += 1
        self._preview_cancel_event.set()
        self._cancel_preview_process()
        self.plot_tabs.blockSignals(True)
        while self.plot_tabs.count() > 0: self.plot_tabs.removeTab(0)
        self.plots.clear()
        self.plot_tabs.blockSignals(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # ウィンドウのサイズ変更だけで再計算せず、描画済みの画像を拡縮する。
        if hasattr(self, 'plot_label'):
            QTimer.singleShot(0, self._show_last_preview)

    def closeEvent(self, event):
        self.update_timer.stop()
        self._preview_generation += 1
        self._preview_cancel_event.set()
        process = self._preview_process
        self._cancel_preview_process()
        if process is not None and process.state() != QProcess.NotRunning:
            process.waitForFinished(1000)  # 終了時だけプロセスの停止を確認
        self._preview_pool.waitForDone()
        self._preview_tempdir.cleanup()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = GnuplotGUIY2Axis()
    window.show()
    sys.exit(app.exec())
