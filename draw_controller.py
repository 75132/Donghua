import sys
import json
import time
import pyautogui
import win32api
import win32con
from PyQt5.QtWidgets import (QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
                           QFileDialog, QLabel, QApplication, QDoubleSpinBox, QGroupBox, QGridLayout, QSpinBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtCore import QSettings

# 添加绘制线程类
class DrawThread(QThread):
    progress = pyqtSignal(int, int)  # 进度信号(当前路径, 总路径)
    finished = pyqtSignal()  # 完成信号
    
    def __init__(self, controller, paths, move_time, pause_time, speed_factor=1.0):
        super().__init__()
        self.controller = controller
        self.paths = paths
        self.move_time = move_time
        self.pause_time = pause_time
        self.speed_factor = speed_factor
        self.is_running = True
        
        # 提高坐标转换精度
        self.transformed_paths = []
        for path in paths:
            transformed_path = []
            last_point = None
            for point in path:
                x, y = controller.transform_point(*point)
                if (x, y) != last_point:
                    transformed_path.append((x, y))
                    last_point = (x, y)
            if transformed_path:
                self.transformed_paths.append(transformed_path)

    def _draw_path(self, path):
        """绘制单个路径"""
        if len(path) < 2:
            return
            
        try:
            # 确保鼠标释放
            pyautogui.mouseUp()
            
            # 精确移动到起点
            x, y = path[0]
            pyautogui.moveTo(x, y)
            
            # 稳定按下鼠标
            pyautogui.mouseDown()
            
            # 根据速度因子调整点的采样间隔
            step = max(1, int(4 * self.speed_factor))  # 速度越快，间隔越大
            
            # 精确绘制每个点
            for i in range(1, len(path), step):
                if not self.is_running:
                    break
                
                x, y = path[i]
                pyautogui.moveTo(x, y, duration=0.0001)  # 保持最快的移动速度
            
            # 确保绘制最后一个点
            if path[-1] != (x, y):
                pyautogui.moveTo(*path[-1], duration=0.0001)
            
            # 完成路径
            pyautogui.mouseUp()
            
        except Exception as e:
            print(f"绘制路径时出错: {str(e)}")

    def run(self):
        try:
            # 禁用pyautogui的自动延迟
            pyautogui.MINIMUM_DURATION = 0
            pyautogui.MINIMUM_SLEEP = 0
            pyautogui.PAUSE = 0
            
            for path_index, path in enumerate(self.transformed_paths):
                if not self.is_running:
                    break
                
                self._draw_path(path)
                self.progress.emit(path_index + 1, len(self.paths))
            
            self.finished.emit()
            
        except Exception as e:
            print(f"绘制出错: {str(e)}")
        finally:
            pyautogui.mouseUp()

    def stop(self):
        self.is_running = False

class MouseListener(QThread):
    right_click = pyqtSignal()  # 右键点击信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True
        self.start()
    
    def run(self):
        while self.is_running:
            # 检测鼠标右键
            if win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000:
                self.right_click.emit()
                # 等待释放右键
                while win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000:
                    QThread.msleep(10)
            QThread.msleep(10)  # 降低CPU使用率
    
    def stop(self):
        self.is_running = False
        self.wait()

class DrawController(QWidget):
    draw_stopped = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("绘制控制器")
        
        # 初始化变量
        self.paths = []
        self.is_drawing = False
        self.draw_thread = None
        self.mouse_listener = None
        self.drawing_area = None
        self.scale = 1.0  # 添加缩放属性初始化
        self.offset_x = 0  # 添加偏移属性初始化
        self.offset_y = 0
        
        # 创建UI
        self.setup_ui()
        
        # 加载设置
        self.settings = QSettings('MyApp', 'DrawController')
        self.load_settings()
        
        # 禁用pyautogui的安全限制
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0
        
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)  # 增加控件间距
        
        # 状态标签
        self.status_label = QLabel("准备就绪")
        self.status_label.setMinimumHeight(30)  # 增加高度
        layout.addWidget(self.status_label)
        
        # 参数控制组
        params_group = QGroupBox("绘制参数")
        params_layout = QGridLayout()
        params_layout.setSpacing(8)  # 设置网格间距
        
        # 移动时间控制
        params_layout.addWidget(QLabel("移动时间:"), 0, 0)
        self.move_time_spin = QDoubleSpinBox()
        self.move_time_spin.setRange(0.001, 0.005)
        self.move_time_spin.setValue(0.001)
        self.move_time_spin.setSingleStep(0.001)
        params_layout.addWidget(self.move_time_spin, 0, 1)
        
        # 停顿时间控制
        params_layout.addWidget(QLabel("停顿时间:"), 1, 0)
        self.pause_time_spin = QDoubleSpinBox()
        self.pause_time_spin.setRange(0.001, 0.010)
        self.pause_time_spin.setValue(0.002)
        self.pause_time_spin.setSingleStep(0.001)
        params_layout.addWidget(self.pause_time_spin, 1, 1)
        
        # 添加速度控制
        params_layout.addWidget(QLabel("绘制速度:"), 2, 0)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0)  # 0.1x - 10x速度
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setSuffix('x')  # 添加单位
        params_layout.addWidget(self.speed_spin, 2, 1)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # 区域控制组
        area_group = QGroupBox("区域控制")
        area_layout = QGridLayout()
        
        # 缩放控制
        area_layout.addWidget(QLabel("缩放比例:"), 0, 0)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 10.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(self.scale)
        self.scale_spin.setDecimals(2)
        area_layout.addWidget(self.scale_spin, 0, 1)
        
        # 偏移控制
        area_layout.addWidget(QLabel("X偏移:"), 1, 0)
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-5000, 5000)
        self.offset_x_spin.setValue(self.offset_x)
        area_layout.addWidget(self.offset_x_spin, 1, 1)
        
        area_layout.addWidget(QLabel("Y偏移:"), 2, 0)
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-5000, 5000)
        self.offset_y_spin.setValue(self.offset_y)
        area_layout.addWidget(self.offset_y_spin, 2, 1)
        
        # 选择区域按钮
        self.select_area_btn = QPushButton("选择绘制区域")
        self.select_area_btn.clicked.connect(self.select_drawing_area)
        area_layout.addWidget(self.select_area_btn, 3, 0, 1, 2)
        
        area_group.setLayout(area_layout)
        layout.addWidget(area_group)
        
        # 按钮组
        button_group = QGroupBox("操作控制")
        button_layout = QVBoxLayout()
        button_layout.setSpacing(8)
        
        # 选择文件按钮
        self.select_btn = QPushButton("选择路径文件")
        self.select_btn.setMinimumHeight(30)
        self.select_btn.clicked.connect(self.select_file)
        button_layout.addWidget(self.select_btn)
        
        # 开始绘制按钮
        self.draw_btn = QPushButton("开始绘制")
        self.draw_btn.setMinimumHeight(30)
        self.draw_btn.clicked.connect(self.start_drawing)
        self.draw_btn.setEnabled(False)
        button_layout.addWidget(self.draw_btn)
        
        button_group.setLayout(button_layout)
        layout.addWidget(button_group)
        
        # 修改提示文本
        tip_label = QLabel("按鼠标右键停止绘制")
        tip_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip_label)
        
        self.setLayout(layout)
        self.setMinimumWidth(300)  # 设置最小宽度
        self.adjustSize()  # 自动调整大小
    
    def load_settings(self):
        """加载保存的设置"""
        self.move_time_spin.setValue(self.settings.value('move_time', 0.001, float))
        self.pause_time_spin.setValue(self.settings.value('pause_time', 0.002, float))
        self.speed_spin.setValue(self.settings.value('speed', 1.0, float))
        self.scale = self.settings.value('scale', 1.0, float)
        self.offset_x = self.settings.value('offset_x', 0, int)
        self.offset_y = self.settings.value('offset_y', 0, int)
        
        # 更新UI控件
        self.scale_spin.setValue(self.scale)
        self.offset_x_spin.setValue(self.offset_x)
        self.offset_y_spin.setValue(self.offset_y)
    
    def save_settings(self):
        """保存当前设置"""
        self.settings.setValue('move_time', self.move_time_spin.value())
        self.settings.setValue('pause_time', self.pause_time_spin.value())
        self.settings.setValue('speed', self.speed_spin.value())
        self.settings.setValue('scale', self.scale_spin.value())
        self.settings.setValue('offset_x', self.offset_x_spin.value())
        self.settings.setValue('offset_y', self.offset_y_spin.value())
    
    def select_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择路径文件",
            "",
            "JSON文件 (*.json)"
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                self.paths = data['paths']
                # 保存原始图像尺寸用于缩放计算
                self.original_width = data['image_size'][1]
                self.original_height = data['image_size'][0]
                self.status_label.setText("路径加载成功")
                self.draw_btn.setEnabled(True)
            except Exception as e:
                self.status_label.setText(f"加载失败: {str(e)}")
    
    def start_drawing(self):
        if not self.paths:
            return
            
        self.is_drawing = True
        self.draw_btn.setEnabled(False)
        self.select_btn.setEnabled(False)
        self.status_label.setText("3秒后开始绘制...")
        
        # 3秒后开始绘制
        QTimer.singleShot(3000, self.start_draw_thread)
    
    def start_draw_thread(self):
        """启动绘制线程"""
        try:
            # 停止现有线程
            self.stop_current_drawing()
            
            # 确保鼠标监听器存在且运行
            if self.mouse_listener is None or not self.mouse_listener.isRunning():
                self.mouse_listener = MouseListener(self)
                self.mouse_listener.right_click.connect(self.stop_current_drawing)
                self.mouse_listener.start()
            
            # 创建新线程
            self.draw_thread = DrawThread(
                self,
                self.paths,
                self.move_time_spin.value(),
                self.pause_time_spin.value(),
                self.speed_spin.value()  # 每次都使用当前的速度值
            )
            self.draw_thread.progress.connect(self.update_progress)
            self.draw_thread.finished.connect(self.on_drawing_finished)
            
            # 更新状态
            self.is_drawing = True
            self.draw_btn.setEnabled(False)
            self.select_btn.setEnabled(False)
            self.status_label.setText("正在绘制...")
            
            # 启动线程
            self.draw_thread.start()
            
        except Exception as e:
            print(f"启动绘制线程时出错: {str(e)}")
            self.stop_current_drawing()
    
    def update_progress(self, current, total):
        """更新进度显示"""
        self.status_label.setText(f"正在绘制: {current}/{total}")
    
    def on_drawing_finished(self):
        """绘制完成处理"""
        self.stop_current_drawing()
    
    def stop_current_drawing(self):
        """停止当前绘制"""
        try:
            self.is_drawing = False
            
            # 停止绘制线程
            if self.draw_thread is not None:
                self.draw_thread.is_running = False
                self.draw_thread.wait(1000)  # 等待最多1秒
                self.draw_thread = None
            
            # 确保鼠标释放
            pyautogui.mouseUp()
            
            # 恢复UI状态
            self.draw_btn.setEnabled(True)
            self.select_btn.setEnabled(True)
            self.status_label.setText("绘制已停止")
            
            # 发送停止信号
            self.draw_stopped.emit()
            
        except Exception as e:
            print(f"停止绘制时出错: {str(e)}")
    
    def stop_all(self):
        """完全停止所有功能"""
        try:
            # 停止绘制
            self.stop_current_drawing()
            
            # 停止鼠标监听
            if self.mouse_listener is not None:
                self.mouse_listener.is_running = False
                self.mouse_listener.wait(1000)
                self.mouse_listener = None
            
            # 保存设置
            self.save_settings()
            
        except Exception as e:
            print(f"停止所有功能时出错: {str(e)}")
    
    def closeEvent(self, event):
        """关闭窗口时的处理"""
        self.stop_all()
        super().closeEvent(event)
    
    def select_drawing_area(self):
        """选择绘制区域"""
        self.hide()  # 暂时隐藏控制窗口
        QTimer.singleShot(500, self._start_area_selection)
    
    def _start_area_selection(self):
        """开始区域选择"""
        try:
            import win32gui
            import win32con
            import tkinter as tk
            
            # 创建选择窗口
            root = tk.Tk()
            root.attributes('-alpha', 0.3)
            root.attributes('-fullscreen', True)
            root.attributes('-topmost', True)
            
            # 存储选择的区域（使用屏幕坐标）
            area = {'x': 0, 'y': 0, 'width': 0, 'height': 0}
            
            def on_mouse_down(event):
                # 获取鼠标的屏幕坐标
                area['x'] = root.winfo_pointerx()
                area['y'] = root.winfo_pointery()
                
            def on_mouse_up(event):
                # 获取鼠标的屏幕坐标
                end_x = root.winfo_pointerx()
                end_y = root.winfo_pointery()
                area['width'] = end_x - area['x']
                area['height'] = end_y - area['y']
                root.destroy()
            
            root.bind('<Button-1>', on_mouse_down)
            root.bind('<ButtonRelease-1>', on_mouse_up)
            root.mainloop()
            
            # 保存选择的区域
            if area['width'] and area['height']:
                self.drawing_area = area
                self.status_label.setText(f"已选择区域: ({area['x']},{area['y']}) {area['width']}x{area['height']}")
            
        except Exception as e:
            print(f"选择区域时出错: {str(e)}")
        finally:
            self.show()
    
    def transform_point(self, x, y):
        """转换坐标点（使用屏幕坐标系）"""
        try:
            # 应用缩放
            scaled_x = x * self.scale_spin.value()
            scaled_y = y * self.scale_spin.value()
            
            if self.drawing_area is not None:
                # 如果选择了区域，将坐标映射到区域内
                # 计算在区域内的相对位置
                rel_x = scaled_x / self.original_width
                rel_y = scaled_y / self.original_height
                
                # 映射到选定区域
                new_x = self.drawing_area['x'] + rel_x * self.drawing_area['width']
                new_y = self.drawing_area['y'] + rel_y * self.drawing_area['height']
            else:
                # 如果没有选择区域，使用原始坐标
                new_x = scaled_x
                new_y = scaled_y
            
            # 应用偏移
            new_x += self.offset_x_spin.value()
            new_y += self.offset_y_spin.value()
            
            return int(new_x), int(new_y)
        except Exception as e:
            print(f"坐标转换出错: {str(e)}")
            return int(x), int(y) 