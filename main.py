import sys
import os
import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QLabel, QSlider, QSpinBox, QGridLayout, QGroupBox, QCheckBox, QSplitter, QDialog, QProgressBar, QDoubleSpinBox, QProgressDialog
from PyQt5.QtGui import QImage, QPixmap, QPainter
from PyQt5.QtCore import Qt, QPoint, QSize, QThread, pyqtSignal, QTimer, QSettings

from image_processor import ImageProcessor
from path_data import PathData
from path_animator import PathAnimator
from export_thread import ExportThread

class ZoomableLabel(QLabel):
    def __init__(self, title="", partner=None):
        super().__init__(title)
        self.setAlignment(Qt.AlignCenter)
        self.scale_factor = 1.0
        self.original_pixmap = None
        self.offset = QPoint(0, 0)
        self.last_mouse_pos = None
        self.partner = partner  # 关联的另一个Label
        
        # 设置固定大小的显示区域
        self.setMinimumSize(500, 300)
        self.setMaximumSize(500, 300)
        
        # 允许鼠标追踪
        self.setMouseTracking(True)
        
    def setPartner(self, partner):
        """设置同步缩放的伙伴Label"""
        self.partner = partner
        
    def setPixmap(self, pixmap):
        """设置图片并保持当前的缩放和偏移"""
        if not hasattr(self, 'original_pixmap'):
            # 第一次设置图片时初始化
            self.original_pixmap = pixmap
            self.offset = QPoint(0, 0)
            self.scale_factor = 1.0
        else:
            # 更新图片但保持当前的缩放和偏移
            current_offset = self.offset
            current_scale = self.scale_factor
            self.original_pixmap = pixmap
            self.offset = current_offset
            self.scale_factor = current_scale
        
        self._update_scaled_pixmap()
        
    def wheelEvent(self, event):
        if self.original_pixmap:
            # 获取鼠标相对于图片的位置
            mouse_pos = event.pos() - self.offset
            
            # 保存旧的缩放因子
            old_factor = self.scale_factor
            
            # 根据滚轮方向调整缩放因子
            delta = event.angleDelta().y()
            if delta > 0:
                self.scale_factor *= 1.1
            else:
                self.scale_factor *= 0.9
            
            # 限制缩放范围
            self.scale_factor = max(0.1, min(5.0, self.scale_factor))
            
            # 调整偏移以保持鼠标位置不变
            if old_factor != self.scale_factor:
                # 更新偏移
                scale_change = self.scale_factor / old_factor
                new_mouse_pos = mouse_pos * scale_change
                self.offset += mouse_pos - new_mouse_pos
                
                # 同步伙伴Label的缩放
                if self.partner:
                    self.partner.scale_factor = self.scale_factor
                    self.partner.offset = self.offset
                    self.partner._update_scaled_pixmap()
                
                self._update_scaled_pixmap()
    
    def mousePressEvent(self, event):
        """记录鼠标按下的位置"""
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.pos()
    
    def mouseReleaseEvent(self, event):
        """清除鼠标位置记录"""
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = None
    
    def mouseMoveEvent(self, event):
        """处理拖动"""
        if self.last_mouse_pos is not None:
            # 计算移动距离
            delta = event.pos() - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = event.pos()
            
            # 同步伙伴Label的偏移
            if self.partner:
                self.partner.offset = self.offset
                self.partner._update_scaled_pixmap()
            
            self._update_scaled_pixmap()
    
    def _update_scaled_pixmap(self):
        """更新显示的图片，处理缩放和偏移"""
        if self.original_pixmap:
            # 计算缩放后的图片大小
            scaled_size = self.original_pixmap.size() * self.scale_factor
            scaled_pixmap = self.original_pixmap.scaled(
                scaled_size,
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            # 创建显示区域大小的空白图片
            display_pixmap = QPixmap(self.size())
            display_pixmap.fill(Qt.black)  # 使用黑色背景
            
            # 在空白图片上绘制缩放后的图片
            painter = QPainter(display_pixmap)
            paint_x = self.offset.x()
            paint_y = self.offset.y()
            painter.drawPixmap(paint_x, paint_y, scaled_pixmap)
            painter.end()
            
            # 显示结果
            super().setPixmap(display_pixmap)

# 添加处理线程类
class ProcessingThread(QThread):
    finished = pyqtSignal(object)
    progress = pyqtSignal(int)
    error = pyqtSignal(str)
    
    def __init__(self, processor, image, operation, params=None):
        super().__init__()
        self.processor = processor
        self.image = image
        self.operation = operation
        self.params = params or {}
        self.is_running = True
    
    def run(self):
        try:
            if not self.is_running:
                return
                
            if self.operation == 'preprocess':
                result = self.processor.preprocess(self.image, **self.params)
                if not self.is_running:
                    return
                self.finished.emit(result)
            elif self.operation == 'skeletonize':
                result = self.processor.skeletonize(self.image)
                if not self.is_running:
                    return
                self.finished.emit(result)
            elif self.operation == 'extract_paths':
                paths, endpoints, crosspoints = self.processor.extract_paths(self.image)
                if not self.is_running:
                    return
                self.finished.emit((paths, endpoints, crosspoints))
            elif self.operation == 'fit_paths':
                result = self.processor.fit_paths(
                    self.params['paths'],
                    self.params['endpoints'],
                    self.params['crosspoints']
                )
                if not self.is_running:
                    return
                self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
            if self.operation == 'extract_paths':
                self.finished.emit(([], [], []))
            else:
                self.finished.emit(self.image)
    
    def stop(self):
        self.is_running = False
        self.wait()  # 等待线程完成

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图像路径提取器")
        self.setMinimumSize(1200, 800)
        
        # 初始化处理器和路径数据对象
        self.processor = ImageProcessor()
        self.path_data = PathData()
        
        # 初始化动画器
        self.animator = PathAnimator()
        
        # 创建主widget和布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        
        # 左侧显示区域 - 使用QSplitter来分割原图和处理后的图像
        left_widget = QSplitter(Qt.Vertical)
        
        # 原图显示
        self.original_label = ZoomableLabel("原图")
        self.original_label.setMinimumHeight(300)
        
        # 处理后图像显示
        self.processed_label = ZoomableLabel("处理后图像")
        self.processed_label.setMinimumHeight(300)
        
        # 建立两个Label的关联
        self.original_label.setPartner(self.processed_label)
        self.processed_label.setPartner(self.original_label)
        
        left_widget.addWidget(self.original_label)
        left_widget.addWidget(self.processed_label)
        main_layout.addWidget(left_widget, stretch=7)
        
        # 右侧控制区域
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 基本操作按钮
        button_group = QGroupBox("基本操作")
        button_layout = QVBoxLayout()
        self.load_btn = QPushButton("加载图像")
        self.preprocess_btn = QPushButton("预处理")
        self.preprocess_btn.setEnabled(False)
        self.skeleton_btn = QPushButton("骨架提取")
        self.skeleton_btn.setEnabled(False)
        self.extract_paths_btn = QPushButton("提取路径")
        self.extract_paths_btn.setEnabled(False)
        self.fit_paths_btn = QPushButton("路径拟合")
        self.fit_paths_btn.setEnabled(False)
        self.save_btn = QPushButton("保存路径")
        self.load_btn_path = QPushButton("加载路径")
        self.save_btn.setEnabled(False)
        self.load_btn_path.setEnabled(True)
        self.load_btn.setShortcut('Ctrl+O')  # 打开图像
        self.save_btn.setShortcut('Ctrl+S')  # 保存路径
        self.draw_btn = QPushButton("绘制控制")
        button_layout.addWidget(self.load_btn)
        button_layout.addWidget(self.preprocess_btn)
        button_layout.addWidget(self.skeleton_btn)
        button_layout.addWidget(self.extract_paths_btn)
        button_layout.addWidget(self.fit_paths_btn)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.load_btn_path)
        button_layout.addWidget(self.draw_btn)
        button_group.setLayout(button_layout)
        right_layout.addWidget(button_group)
        
        # 预处理参数控制
        param_group = QGroupBox("预处理参数")
        param_layout = QGridLayout()
        
        # 二值化参数
        param_layout.addWidget(QLabel("二值化阈值:"), 0, 0)
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(0, 255)
        self.threshold_slider.setValue(127)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 255)
        self.threshold_spin.setValue(127)
        param_layout.addWidget(self.threshold_slider, 0, 1)
        param_layout.addWidget(self.threshold_spin, 0, 2)
        
        # 降噪参数
        param_layout.addWidget(QLabel("降噪强度:"), 1, 0)
        self.noise_slider = QSlider(Qt.Horizontal)
        self.noise_slider.setRange(1, 10)
        self.noise_slider.setValue(3)
        self.noise_spin = QSpinBox()
        self.noise_spin.setRange(1, 10)
        self.noise_spin.setValue(3)
        param_layout.addWidget(self.noise_slider, 1, 1)
        param_layout.addWidget(self.noise_spin, 1, 2)
        
        # 实时预览复选框
        self.preview_checkbox = QCheckBox("实时预览")
        param_layout.addWidget(self.preview_checkbox, 2, 0, 1, 3)
        
        # 在预处理参数组中添加自动执行选项
        self.auto_process_checkbox = QCheckBox("自动执行后续步骤")
        self.auto_process_checkbox.setChecked(True)  # 默认开启
        param_layout.addWidget(self.auto_process_checkbox, 3, 0, 1, 3)
        
        # 移动细化迭代控制到新的行
        param_layout.addWidget(QLabel("细化迭代:"), 4, 0)
        self.thin_iter_spin = QSpinBox()
        self.thin_iter_spin.setRange(1, 100)
        self.thin_iter_spin.setValue(50)
        param_layout.addWidget(self.thin_iter_spin, 4, 1)
        
        # 添加自动保存设置
        self.auto_save = QCheckBox("自动保存")
        self.auto_save.setChecked(False)
        param_layout.addWidget(self.auto_save, 5, 0, 1, 3)
        
        param_group.setLayout(param_layout)
        right_layout.addWidget(param_group)
        
        # 修改拟合参数控制组
        fit_params_group = QGroupBox("拟合参数")
        fit_params_layout = QGridLayout()
        
        # 直线判定阈值控制
        fit_params_layout.addWidget(QLabel("直线判定阈值:"), 0, 0)
        self.line_threshold_spin = QDoubleSpinBox()
        self.line_threshold_spin.setRange(0.0, 2.0)
        self.line_threshold_spin.setSingleStep(0.01)
        self.line_threshold_spin.setDecimals(2)
        self.line_threshold_spin.setValue(0.98)
        fit_params_layout.addWidget(self.line_threshold_spin, 0, 1)
        
        # 控制点距离因子控制
        fit_params_layout.addWidget(QLabel("控制点距离:"), 1, 0)
        self.control_dist_spin = QDoubleSpinBox()
        self.control_dist_spin.setRange(0.0, 2.0)
        self.control_dist_spin.setSingleStep(0.01)
        self.control_dist_spin.setDecimals(2)
        self.control_dist_spin.setValue(0.25)
        fit_params_layout.addWidget(self.control_dist_spin, 1, 1)
        
        # 拟合控制按钮
        fit_control_layout = QHBoxLayout()
        self.fit_enabled_checkbox = QCheckBox("启用拟合")
        self.fit_preview_btn = QPushButton("预览")
        self.fit_apply_btn = QPushButton("应用")
        self.fit_preview_btn.setEnabled(False)
        self.fit_apply_btn.setEnabled(False)
        
        fit_control_layout.addWidget(self.fit_enabled_checkbox)
        fit_control_layout.addWidget(self.fit_preview_btn)
        fit_control_layout.addWidget(self.fit_apply_btn)
        fit_params_layout.addLayout(fit_control_layout, 2, 0, 1, 2)
        
        fit_params_group.setLayout(fit_params_layout)
        right_layout.addWidget(fit_params_group)
        
        # 修改进度显示组件
        self.progress_group = QGroupBox("处理进度")
        progress_layout = QVBoxLayout()
        self.progress_label = QLabel("就绪")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        self.progress_group.setLayout(progress_layout)
        right_layout.addWidget(self.progress_group)
        
        # 添加自动缩放参数
        self.max_image_size = 1000  # 最大图像尺寸
        
        # 添加防抖定时器
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._delayed_preview)
        
        # 添加处理超时定时器
        self.process_timer = QTimer()
        self.process_timer.setSingleShot(True)
        self.process_timer.timeout.connect(self.handle_timeout)
        
        # 初始化其他变量
        self.processing_thread = None
        self.current_image = None
        self.last_directory = os.path.expanduser("~")
        self.preview_pending = False
        
        # 设置实时预览默认开启
        self.preview_checkbox.setChecked(True)
        
        # 添加动画控制组
        animation_group = QGroupBox("轨迹预览")
        animation_layout = QGridLayout()
        
        # 添加动画控制按钮
        self.play_btn = QPushButton("播放")
        self.pause_btn = QPushButton("暂停")
        self.stop_btn = QPushButton("停止")
        self.play_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.play_btn.setShortcut('Space')   # 播放/暂停
        self.stop_btn.setShortcut('Esc')     # 停止
        
        # 修改速度控制
        animation_layout.addWidget(QLabel("播放速度(x):"), 0, 0)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0)
        self.speed_spin.setSingleStep(0.5)
        self.speed_spin.setValue(1.0)
        animation_layout.addWidget(self.speed_spin, 0, 1)
        
        # 添加端点显示控制
        self.show_points_checkbox = QCheckBox("显示端点")
        self.show_points_checkbox.setChecked(False)
        animation_layout.addWidget(self.show_points_checkbox, 0, 2)
        
        # 添加按钮到布局
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.play_btn)
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.stop_btn)
        animation_layout.addLayout(button_layout, 1, 0, 1, 2)
        
        # 添加导出按钮到动画控制组
        self.export_btn = QPushButton("导出动画")
        self.export_btn.setEnabled(False)
        button_layout.addWidget(self.export_btn)
        
        animation_group.setLayout(animation_layout)
        right_layout.addWidget(animation_group)
        
        # 添加弹性空间
        right_layout.addStretch()
        main_layout.addWidget(right_widget, stretch=3)
        
        # 连接信号和槽
        self.setup_connections()
        
        # 存储提取的路径数据
        self.paths = []
        self.endpoints = []
        self.crosspoints = []
        
        # 存储拟合后的路径
        self.fitted_paths = []
        
        # 初始化路径数据对象
        self.path_data = PathData()
        
        # 初始化动画器
        self.animator = PathAnimator()
        self.animator.frame_ready.connect(
            lambda frame: self.display_image(frame, self.processed_label))
        
        # 添加线程列表用于管理
        self.threads = []
        
        # 添加最近文件列表
        self.recent_files = []
        self.max_recent_files = 5
        self.load_recent_files()
        
        # 启用拖放
        self.setAcceptDrops(True)
        
        # 创建绘制控制器（但不显示）
        self.draw_controller = None
        
    def setup_connections(self):
        # 按钮连接
        self.load_btn.clicked.connect(self.load_image)
        self.preprocess_btn.clicked.connect(self.preprocess_image)
        self.skeleton_btn.clicked.connect(self.extract_skeleton)
        self.extract_paths_btn.clicked.connect(self.extract_paths)
        self.fit_paths_btn.clicked.connect(self.fit_paths)
        self.save_btn.clicked.connect(self.save_path_data)
        self.load_btn_path.clicked.connect(self.load_path_data)
        self.draw_btn.clicked.connect(self.show_draw_controller)
        
        # 参数控件连接
        self.threshold_slider.valueChanged.connect(lambda: self.on_param_changed(False))
        self.threshold_spin.valueChanged.connect(lambda: self.on_param_changed(False))
        self.noise_slider.valueChanged.connect(lambda: self.on_param_changed(False))
        self.noise_spin.valueChanged.connect(lambda: self.on_param_changed(False))
        
        # 预览复选框状态改变时立即更新
        self.preview_checkbox.stateChanged.connect(lambda: self.on_param_changed(True))
        
        # 更新拟合参数连接
        self.line_threshold_spin.valueChanged.connect(self.preview_fit_paths)
        self.control_dist_spin.valueChanged.connect(self.preview_fit_paths)
        self.fit_enabled_checkbox.stateChanged.connect(self.preview_fit_paths)
        self.fit_preview_btn.clicked.connect(self.preview_fit_paths)
        self.fit_apply_btn.clicked.connect(self.apply_fit_paths)
        
        # 动画控制按钮连接
        self.play_btn.clicked.connect(self.play_animation)
        self.pause_btn.clicked.connect(self.pause_animation)
        self.stop_btn.clicked.connect(self.stop_animation)
        self.speed_spin.valueChanged.connect(self.update_animation_speed)
        self.show_points_checkbox.stateChanged.connect(
            lambda state: self.animator.set_show_points(state == Qt.Checked))
        
        # 动画完成信号连接
        self.animator.animation_finished.connect(self.on_animation_finished)
        
        # 添加导出按钮连接
        self.export_btn.clicked.connect(self.export_animation)
    
    def load_image(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, 
            "选择图像", 
            self.last_directory,
            "图像文件 (*.png *.jpg *.bmp)"
        )
        if file_name:
            self.last_directory = os.path.dirname(file_name)
            self.current_image = self.processor.load_image(file_name)
            
            if self.current_image is not None:
                h, w = self.current_image.shape[:2]
                if h * w > 4000 * 4000:  # 限制最大像素数
                    self.handle_error("图像太大，请使用小于4000x4000像素的图像")
                    return
                # 自动缩放大图像
                if max(h, w) > self.max_image_size:
                    scale = self.max_image_size / max(h, w)
                    new_size = (int(w * scale), int(h * scale))
                    self.current_image = cv2.resize(self.current_image, new_size)
                    self.progress_label.setText(f"图像已自动缩放至 {new_size[0]}x{new_size[1]}")
                
                self.display_image(self.current_image, self.original_label)
                self.preprocess_btn.setEnabled(True)
                self.preprocess_image()
    
    def start_processing(self, operation, image=None, params=None):
        # 添加线程安全检查
        if hasattr(self, 'processing_thread') and self.processing_thread:
            try:
                self.processing_thread.stop()
                self.processing_thread.wait(1000)  # 等待最多1秒
                if self.processing_thread.isRunning():
                    print("警告：无法停止之前的处理线程")
                    return
            except Exception as e:
                print(f"停止线程时出错: {str(e)}")
                return
        
        # 禁用所有处理按钮
        self.preprocess_btn.setEnabled(False)
        self.skeleton_btn.setEnabled(False)
        self.extract_paths_btn.setEnabled(False)
        self.fit_paths_btn.setEnabled(False)
        
        # 显示进度条
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        # 设置进度标签
        operation_names = {
            'preprocess': "预处理",
            'skeletonize': "骨架提取",
            'extract_paths': "路径提取",
            'fit_paths': "路径拟合"
        }
        operation_name = operation_names.get(operation, operation)
        self.progress_label.setText(f"正在{operation_name}...")
        
        # 创建并启动处理线程
        self.processing_thread = ProcessingThread(
            self.processor,
            self.current_image if image is None else image,
            operation,
            params
        )
        self.processing_thread.finished.connect(self.on_processing_finished)
        self.processing_thread.error.connect(self.handle_error)
        self.threads.append(self.processing_thread)  # 添加到线程列表
        self.processing_thread.start()
        
        # 启动超时定时器 - 增加到60秒
        self.process_timer.start(60000)  # 60秒超时
    
    def handle_timeout(self):
        """处理超时"""
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.stop()
            self.progress_label.setText("处理超时，已终止")
            self.reset_ui()
    
    def handle_error(self, error_msg):
        """处理错误"""
        print(f"错误: {error_msg}")  # 添加日志
        self.progress_label.setText(f"处理出错: {error_msg}")
        self.progress_bar.hide()
        self.reset_ui()
        
        # 如果是严重错误，清理相关数据
        if "内存不足" in error_msg or "访问冲突" in error_msg:
            self.current_image = None
            self.processed_image = None
            self.skeleton_image = None
    
    def reset_ui(self):
        """重置UI状态"""
        self.check_state()  # 添加状态检查
        self.preprocess_btn.setEnabled(True)
        if hasattr(self, 'processed_image'):
            self.skeleton_btn.setEnabled(True)
        if hasattr(self, 'skeleton_image'):
            self.extract_paths_btn.setEnabled(True)
        if hasattr(self, 'paths'):  # 只要有路径数据就启用保存按钮
            self.save_btn.setEnabled(True)
        if hasattr(self, 'fitted_paths'):
            self.fit_paths_btn.setEnabled(True)
        self.progress_bar.hide()
        
    def on_processing_finished(self, result):
        """处理完成的回调"""
        try:
            # 停止超时定时器
            self.process_timer.stop()
            
            # 隐藏进度条
            self.progress_bar.hide()
            
            # 更新进度标签
            self.progress_label.setText("处理完成")
            
            # 更新图像显示和状态
            if self.processing_thread.operation == 'preprocess':
                self.processed_image = result
                self.display_image(result, self.processed_label)
                self.skeleton_btn.setEnabled(True)
                
                # 如果启用了自动执行，延迟一小段时间后执行骨架提取
                if self.auto_process_checkbox.isChecked():
                    QTimer.singleShot(100, self.extract_skeleton)
                    
            elif self.processing_thread.operation == 'skeletonize':
                self.skeleton_image = result
                self.display_image(result, self.processed_label)
                self.extract_paths_btn.setEnabled(True)
                
                # 如果启用了自动执行，延迟一小段时间后执行路径提取
                if self.auto_process_checkbox.isChecked():
                    QTimer.singleShot(100, self.extract_paths)
                    
            elif self.processing_thread.operation == 'extract_paths':
                self.paths, self.endpoints, self.crosspoints = result
                vis_image = self.processor.visualize_paths(
                    self.skeleton_image.shape,
                    self.paths,
                    self.endpoints,
                    self.crosspoints
                )
                self.display_image(vis_image, self.processed_label)
                
                # 启用相关按钮
                self.save_btn.setEnabled(True)
                self.play_btn.setEnabled(True)
                self.stop_btn.setEnabled(True)
                self.export_btn.setEnabled(True)
                
                # 设置动画数据
                self.animator.set_data(
                    self.paths,
                    self.endpoints,
                    self.crosspoints,
                    self.skeleton_image.shape
                )
                
            elif self.processing_thread.operation == 'fit_paths':
                self.fitted_paths = result
                vis_image = self.processor.visualize_fitted_paths(
                    self.skeleton_image.shape,
                    self.fitted_paths,
                    self.endpoints,
                    self.crosspoints
                )
                self.display_image(vis_image, self.processed_label)
            
            # 自动保存功能
            if self.auto_save.isChecked() and hasattr(self, 'paths'):
                auto_save_file = os.path.join(
                    self.last_directory,
                    'auto_save.json'
                )
                self.path_data.add_path_data(
                    self.paths,
                    self.endpoints,
                    self.crosspoints,
                    self.skeleton_image.shape
                )
                if hasattr(self, 'fitted_paths'):
                    self.path_data.add_fitted_paths(self.fitted_paths)
                self.path_data.save_to_file(auto_save_file)
            
        except Exception as e:
            print(f"处理完成回调出错: {str(e)}")
            self.handle_error(str(e))
    
    def preprocess_image(self):
        if self.current_image is not None:
            params = {
                'threshold': self.threshold_slider.value(),
                'noise_kernel_size': self.noise_slider.value()
            }
            self.start_processing('preprocess', params=params)
    
    def on_param_changed(self, force_update=False):
        """参数改变时的处理"""
        if self.preview_checkbox.isChecked() and self.current_image is not None:
            if force_update:
                # 立即更新
                self.preprocess_image()
            else:
                # 使用定时器延迟更新，避免频繁刷新
                self.preview_timer.start(200)  # 200ms延迟
                self.preview_pending = True
    
    def _delayed_preview(self):
        """延迟执行预览更新"""
        if self.preview_pending:
            self.preprocess_image()
            self.preview_pending = False
    
    def display_image(self, image, label):
        """改进的图像显示函数"""
        if image is None:
            return
            
        height, width = image.shape[:2]
        bytes_per_line = 3 * width
        
        # 使用numpy的copy()方法复制数据
        image_data = np.array(image).copy()
        q_image = QImage(image_data.data, width, height, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)
        
        # 设置原始大小的pixmap，缩放由ZoomableLabel处理
        label.setPixmap(pixmap)
        # 强制更新显示
        label.update()
    
    def extract_skeleton(self):
        """执行骨架提取"""
        if hasattr(self, 'processed_image'):
            self.start_processing('skeletonize', self.processed_image)
    
    def extract_paths(self):
        """执行路径提取"""
        if hasattr(self, 'skeleton_image'):
            self.start_processing('extract_paths', self.skeleton_image)
    
    def fit_paths(self):
        """执行路径拟合"""
        if hasattr(self, 'paths'):
            self.start_processing('fit_paths', None, {
                'paths': self.paths,
                'endpoints': self.endpoints,
                'crosspoints': self.crosspoints
            })
    
    def preview_fit_paths(self):
        """预览路径拟合结果"""
        if not hasattr(self, 'paths'):
            return
        
        if self.fit_enabled_checkbox.isChecked():
            # 获取当前参数
            line_threshold = self.line_threshold_spin.value()
            control_dist = self.control_dist_spin.value()
            
            # 执行拟合并预览
            fitted_paths = self.processor.fit_paths(
                self.paths,
                self.endpoints,
                self.crosspoints,
                line_threshold=line_threshold,
                control_dist_factor=control_dist
            )
            
            # 显示拟合预览
            vis_image = self.processor.visualize_fitted_paths(
                self.skeleton_image.shape,
                fitted_paths,
                self.endpoints,
                self.crosspoints
            )
            self.display_image(vis_image, self.processed_label)
            
            # 临时保存拟合结果以供应用
            self.preview_fitted_paths = fitted_paths
        else:
            # 显示原始路径
            vis_image = self.processor.visualize_paths(
                self.skeleton_image.shape,
                self.paths,
                self.endpoints,
                self.crosspoints
            )
            self.display_image(vis_image, self.processed_label)

    def apply_fit_paths(self):
        """应用路径拟合结果"""
        if hasattr(self, 'preview_fitted_paths'):
            self.fitted_paths = self.preview_fitted_paths
            self.save_btn.setEnabled(True)
            self.progress_label.setText("路径拟合已应用")
    
    def save_path_data(self):
        """保存路径数据"""
        if not hasattr(self, 'paths'):
            return
            
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "保存路径数据",
            self.last_directory,
            "JSON文件 (*.json)"
        )
        
        if filename:
            self.path_data.add_path_data(
                self.paths,
                self.endpoints,
                self.crosspoints,
                self.skeleton_image.shape
            )
            if hasattr(self, 'fitted_paths'):
                self.path_data.add_fitted_paths(self.fitted_paths)
            
            if self.path_data.save_to_file(filename):
                self.progress_label.setText("路径数据保存成功")
            else:
                self.progress_label.setText("保存路径数据失败")
    
    def load_path_data(self):
        """加载路径数据"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "加载路径数据",
            self.last_directory,
            "JSON文件 (*.json)"
        )
        
        if filename:
            if self.path_data.load_from_file(filename):
                self.paths = self.path_data.paths
                self.endpoints = self.path_data.endpoints
                self.crosspoints = self.path_data.crosspoints
                self.fitted_paths = self.path_data.fitted_paths
                
                # 创建空白图像用于显示
                self.skeleton_image = np.zeros(
                    (*self.path_data.image_size[:2], 3),
                    dtype=np.uint8
                )
                
                # 显示路径
                if self.fit_enabled_checkbox.isChecked() and self.fitted_paths:
                    vis_image = self.processor.visualize_fitted_paths(
                        self.skeleton_image.shape,
                        self.fitted_paths,
                        self.endpoints,
                        self.crosspoints
                    )
                else:
                    vis_image = self.processor.visualize_paths(
                        self.skeleton_image.shape,
                        self.paths,
                        self.endpoints,
                        self.crosspoints
                    )
                self.display_image(vis_image, self.processed_label)
                
                self.progress_label.setText("路径数据加载成功")
                self.save_btn.setEnabled(True)
                self.play_btn.setEnabled(True)
                self.stop_btn.setEnabled(True)
                # 设置动画数据
                self.animator.set_data(
                    self.paths,
                    self.endpoints,
                    self.crosspoints,
                    self.skeleton_image.shape
                )
            else:
                self.progress_label.setText("加载路径数据失败")
    
    def play_animation(self):
        """开始播放动画"""
        self.animator.play()
        self.play_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

    def pause_animation(self):
        """暂停动画"""
        self.animator.pause()
        self.play_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_animation(self):
        """停止动画"""
        self.animator.stop()
        self.play_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def update_animation_speed(self, value):
        """更新动画速度"""
        self.animator.set_speed(value)

    def on_animation_finished(self):
        """动画播放完成的处理"""
        self.play_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def closeEvent(self, event):
        """窗口关闭时的处理"""
        try:
            # 停止所有定时器
            self.preview_timer.stop()
            self.process_timer.stop()
            
            # 停止动画
            self.animator.stop()
            
            # 停止并等待所有线程
            for thread in self.threads:
                if thread and thread.isRunning():
                    thread.stop()
                    thread.wait(1000)  # 添加超时
            
            # 清理大型数据
            self.current_image = None
            self.processed_image = None
            self.skeleton_image = None
            self.paths = []
            self.endpoints = []
            self.crosspoints = []
            self.fitted_paths = []
            
            # 保存最近文件列表
            self.save_recent_files()
            
            event.accept()
        except Exception as e:
            print(f"关闭窗口时出错: {str(e)}")
            event.accept()

    def export_animation(self):
        """导出动画为视频文件"""
        if not hasattr(self, 'paths'):
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出动画",
            self.last_directory,
            "视频文件 (*.mp4);;GIF动画 (*.gif)"
        )
        
        if filename:
            self.progress_label.setText("正在导出动画...")
            self.progress_bar.show()
            
            # 创建导出线程
            self.export_thread = ExportThread(
                self.animator,
                filename,
                self.speed_spin.value()
            )
            self.export_thread.progress.connect(self.progress_bar.setValue)
            self.export_thread.finished.connect(self._on_export_finished)
            self.export_thread.error.connect(self.handle_error)
            self.threads.append(self.export_thread)  # 添加到线程列表
            self.export_thread.start()

    def _on_export_finished(self, success):
        """导出完成的处理"""
        self.progress_bar.hide()
        if success:
            self.progress_label.setText("动画导出成功")
        else:
            self.progress_label.setText("动画导出失败")

    def check_state(self):
        """检查程序状态"""
        if not hasattr(self, 'current_image') or self.current_image is None:
            self.preprocess_btn.setEnabled(False)
            return False
        
        if not hasattr(self, 'processed_image') or self.processed_image is None:
            self.skeleton_btn.setEnabled(False)
            return False
        
        if not hasattr(self, 'skeleton_image') or self.skeleton_image is None:
            self.extract_paths_btn.setEnabled(False)
            return False
        
        return True

    def load_recent_files(self):
        """加载最近文件列表"""
        try:
            settings = QSettings('YourCompany', 'PathExtractor')
            self.recent_files = settings.value('recentFiles', [], str)
        except Exception as e:
            print(f"加载最近文件列表出错: {str(e)}")

    def save_recent_files(self):
        """保存最近文件列表"""
        try:
            settings = QSettings('YourCompany', 'PathExtractor')
            settings.setValue('recentFiles', self.recent_files)
        except Exception as e:
            print(f"保存最近文件列表出错: {str(e)}")

    def update_recent_files(self, filename):
        """更新最近文件列表"""
        if filename in self.recent_files:
            self.recent_files.remove(filename)
        self.recent_files.insert(0, filename)
        if len(self.recent_files) > self.max_recent_files:
            self.recent_files = self.recent_files[:self.max_recent_files]
        self.save_recent_files()

    def dragEnterEvent(self, event):
        """处理拖入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """处理放下事件"""
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.png', '.jpg', '.bmp')):
                self.load_image_from_path(file_path)
            elif file_path.lower().endswith('.json'):
                self.load_path_data_from_path(file_path)

    def batch_process(self):
        """批量处理图像"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择图像目录",
            self.last_directory
        )
        
        if directory:
            # 获取所有图像文件
            image_files = [
                f for f in os.listdir(directory)
                if f.lower().endswith(('.png', '.jpg', '.bmp'))
            ]
            
            if not image_files:
                self.handle_error("所选目录没有支持的图像文件")
                return
            
            # 创建进度对话框
            progress = QProgressDialog(
                "正在批量处理...",
                "取消",
                0,
                len(image_files),
                self
            )
            progress.setWindowModality(Qt.WindowModal)
            
            # 处理每个文件
            for i, file_name in enumerate(image_files):
                if progress.wasCanceled():
                    break
                    
                file_path = os.path.join(directory, file_name)
                self.load_image_from_path(file_path)
                # 等待处理完成
                QApplication.processEvents()
                
                progress.setValue(i + 1)

    def save_settings(self):
        """保存当前设置"""
        settings = QSettings('YourCompany', 'PathExtractor')
        settings.setValue('threshold', self.threshold_slider.value())
        settings.setValue('noise', self.noise_slider.value())
        settings.setValue('preview', self.preview_checkbox.isChecked())
        settings.setValue('auto_process', self.auto_process_checkbox.isChecked())
        settings.setValue('line_threshold', self.line_threshold_spin.value())
        settings.setValue('control_dist', self.control_dist_spin.value())
        settings.setValue('last_directory', self.last_directory)

    def load_settings(self):
        """加载保存的设置"""
        settings = QSettings('YourCompany', 'PathExtractor')
        self.threshold_slider.setValue(settings.value('threshold', 127, int))
        self.noise_slider.setValue(settings.value('noise', 3, int))
        self.preview_checkbox.setChecked(settings.value('preview', True, bool))
        self.auto_process_checkbox.setChecked(settings.value('auto_process', True, bool))
        self.line_threshold_spin.setValue(settings.value('line_threshold', 0.98, float))
        self.control_dist_spin.setValue(settings.value('control_dist', 0.25, float))
        self.last_directory = settings.value('last_directory', os.path.expanduser("~"))

    def load_image_from_path(self, file_path):
        """从指定路径加载图像"""
        try:
            # 更新最后使用的目录
            self.last_directory = os.path.dirname(file_path)
            
            # 加载图像
            image = self.processor.load_image(file_path)
            if image is not None:
                self.current_image = image
                # 自动缩放大图像
                h, w = self.current_image.shape[:2]
                if h * w > 4000 * 4000:  # 限制最大像素数
                    self.handle_error("图像太大，请使用小于4000x4000像素的图像")
                    return
                    
                if max(h, w) > self.max_image_size:
                    scale = self.max_image_size / max(h, w)
                    new_size = (int(w * scale), int(h * scale))
                    self.current_image = cv2.resize(
                        self.current_image,
                        new_size,
                        interpolation=cv2.INTER_AREA
                    )
                
                # 显示图像
                self.display_image(self.current_image, self.original_label)
                self.preprocess_btn.setEnabled(True)
                self.progress_label.setText("图像加载成功")
                
                # 更新最近文件列表
                self.update_recent_files(file_path)
            else:
                self.progress_label.setText("图像加载失败")
        except Exception as e:
            self.handle_error(f"加载图像时出错: {str(e)}")

    def load_path_data_from_path(self, file_path):
        """从指定路径加载路径数据"""
        try:
            # 更新最后使用的目录
            self.last_directory = os.path.dirname(file_path)
            
            if self.path_data.load_from_file(file_path):
                self.paths = self.path_data.paths
                self.endpoints = self.path_data.endpoints
                self.crosspoints = self.path_data.crosspoints
                self.fitted_paths = self.path_data.fitted_paths
                
                # 创建空白图像用于显示
                self.skeleton_image = np.zeros(
                    (*self.path_data.image_size[:2], 3),
                    dtype=np.uint8
                )
                
                # 显示路径
                if hasattr(self, 'fit_enabled_checkbox') and \
                   self.fit_enabled_checkbox.isChecked() and \
                   self.fitted_paths:
                    vis_image = self.processor.visualize_fitted_paths(
                        self.skeleton_image.shape,
                        self.fitted_paths,
                        self.endpoints,
                        self.crosspoints
                    )
                else:
                    vis_image = self.processor.visualize_paths(
                        self.skeleton_image.shape,
                        self.paths,
                        self.endpoints,
                        self.crosspoints
                    )
                self.display_image(vis_image, self.processed_label)
                
                self.progress_label.setText("路径数据加载成功")
                self.save_btn.setEnabled(True)
                self.play_btn.setEnabled(True)
                self.stop_btn.setEnabled(True)
                
                # 设置动画数据
                self.animator.set_data(
                    self.paths,
                    self.endpoints,
                    self.crosspoints,
                    self.skeleton_image.shape
                )
                
                # 更新最近文件列表
                self.update_recent_files(file_path)
            else:
                self.progress_label.setText("加载路径数据失败")
        except Exception as e:
            self.handle_error(f"加载路径数据时出错: {str(e)}")

    def show_draw_controller(self):
        """显示绘制控制器"""
        if self.draw_controller is None:
            from draw_controller import DrawController
            self.draw_controller = DrawController()
            self.draw_controller.draw_stopped.connect(self.on_draw_stopped)
        self.draw_controller.show()

    def on_draw_stopped(self):
        """绘制停止的处理"""
        self.progress_label.setText("绘制已停止")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_()) 