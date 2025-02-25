import sys
import json
import numpy as np
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel, QScrollArea, QHBoxLayout
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QMouseEvent
from PyQt5.QtCore import Qt, QPoint, QRect

class ZoomableLabel(QLabel):
    def __init__(self, main_window):
        super().__init__()
        self.setMinimumSize(800, 600)
        self.setAlignment(Qt.AlignCenter)
        
        # 保存主窗口引用
        self.main_window = main_window
        
        # 缩放和拖动相关变量
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0)
        self.last_mouse_pos = None
        self.original_pixmap = None
        
        # 编辑相关变量
        self.selected_point = None
        self.selected_path_index = -1
        self.selected_point_index = -1
        self.hover_point = None
        self.hover_path_index = -1
        self.hover_point_index = -1
        self.point_radius = 5
        
        # 允许鼠标追踪
        self.setMouseTracking(True)
        
        # 添加选中路径标记
        self.keep_selection = False    # 保持选中状态
    
    def setPixmap(self, pixmap):
        """重写setPixmap方法"""
        self.original_pixmap = pixmap
        self._update_scaled_pixmap()
    
    def wheelEvent(self, event):
        """处理滚轮事件实现缩放"""
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
            self.scale_factor = max(0.1, min(10.0, self.scale_factor))
            
            # 调整偏移以保持鼠标位置不变
            if old_factor != self.scale_factor:
                scale_change = self.scale_factor / old_factor
                new_mouse_pos = mouse_pos * scale_change
                self.offset += mouse_pos - new_mouse_pos
                
                self._update_scaled_pixmap()
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.hover_point is not None:
                # 选中点和路径
                self.selected_point = self.hover_point
                self.selected_path_index = self.hover_path_index
                self.selected_point_index = self.hover_point_index
                self.keep_selection = True
                self._update_scaled_pixmap()
            else:
                # 拖动视图
                self.last_mouse_pos = event.pos()
        elif event.button() == Qt.RightButton:
            # 右键取消选中
            self.clear_selection()
            self._update_scaled_pixmap()
    
    def clear_selection(self):
        """清除选中状态"""
        self.selected_point = None
        self.selected_path_index = -1
        self.selected_point_index = -1
        self.hover_point = None
        self.hover_path_index = -1
        self.hover_point_index = -1
        self.keep_selection = False
        # 更新删除按钮状态
        self.main_window.delete_btn.setEnabled(False)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = None
            if not self.keep_selection:
                self.selected_point = None
                self.selected_path_index = -1
                self.selected_point_index = -1
    
    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.pos()
        
        if self.selected_point is not None:
            # 移动选中的点
            screen_pos = (pos - self.offset) / self.scale_factor
            self.main_window.update_point(
                self.selected_path_index,
                self.selected_point_index,
                screen_pos.x(),
                screen_pos.y()
            )
        elif self.last_mouse_pos is not None:
            # 拖动视图
            delta = pos - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = pos
            self._update_scaled_pixmap()
        else:
            # 检测鼠标悬停
            self.check_hover_point(pos)
    
    def check_hover_point(self, pos):
        """检查鼠标是否悬停在端点上"""
        screen_pos = (pos - self.offset) / self.scale_factor
        old_hover = (self.hover_point, self.hover_path_index, self.hover_point_index)
        
        if not self.keep_selection:
            self.hover_point = None
            self.hover_path_index = -1
            self.hover_point_index = -1
            
            for path_idx, path in enumerate(self.main_window.paths):
                if not path:
                    continue
                    
                # 检查起点和终点
                start_point = QPoint(*path[0])
                if (start_point - screen_pos).manhattanLength() < self.point_radius:
                    self.hover_point = start_point
                    self.hover_path_index = path_idx
                    self.hover_point_index = 0
                    break
                
                end_point = QPoint(*path[-1])
                if (end_point - screen_pos).manhattanLength() < self.point_radius:
                    self.hover_point = end_point
                    self.hover_path_index = path_idx
                    self.hover_point_index = len(path) - 1
                    break
        
        if old_hover != (self.hover_point, self.hover_path_index, self.hover_point_index):
            self._update_scaled_pixmap()
        
        # 更新删除按钮状态
        self.main_window.delete_btn.setEnabled(
            self.hover_path_index >= 0 or self.selected_path_index >= 0
        )
    
    def _update_scaled_pixmap(self):
        """更新显示的图片"""
        if self.original_pixmap:
            # 计算缩放后的图片大小
            scaled_size = self.original_pixmap.size() * self.scale_factor
            scaled_pixmap = self.original_pixmap.scaled(
                scaled_size,  # 直接使用QSize对象
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # 创建显示区域大小的空白图片
            display_pixmap = QPixmap(self.size())
            display_pixmap.fill(Qt.black)
            
            # 在空白图片上绘制缩放后的图片
            painter = QPainter(display_pixmap)
            paint_x = self.offset.x()
            paint_y = self.offset.y()
            painter.drawPixmap(paint_x, paint_y, scaled_pixmap)
            painter.end()
            
            # 显示结果
            super().setPixmap(display_pixmap)

class PathPreview(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("路径预览器")
        
        # 初始化变量
        self.paths = []
        self.image_size = None
        self.history = []  # 添加历史记录
        
        # 创建主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # 创建布局
        layout = QVBoxLayout(main_widget)
        
        # 创建按钮布局
        button_layout = QHBoxLayout()
        
        # 加载按钮
        load_btn = QPushButton("加载JSON")
        load_btn.clicked.connect(self.load_json)
        button_layout.addWidget(load_btn)
        
        # 保存按钮
        save_btn = QPushButton("保存JSON")
        save_btn.clicked.connect(self.save_json)
        button_layout.addWidget(save_btn)
        
        # 删除选中路径按钮
        self.delete_btn = QPushButton("删除选中路径")
        self.delete_btn.clicked.connect(self.delete_selected_path)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)
        
        # 添加撤销按钮
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.setEnabled(False)
        button_layout.addWidget(self.undo_btn)
        
        # 路径数量标签
        self.path_count_label = QLabel("路径数量: 0")
        button_layout.addWidget(self.path_count_label)
        
        layout.addLayout(button_layout)
        
        # 创建可缩放的预览区域
        self.preview_label = ZoomableLabel(self)
        layout.addWidget(self.preview_label)
        
        # 设置窗口大小
        self.resize(1000, 800)

    def load_json(self):
        """加载JSON文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择JSON文件",
            "",
            "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.paths = data['paths']
                self.image_size = data['image_size']
                
                # 更新路径数量显示
                self.update_path_count()
                self.draw_preview()
                
            except Exception as e:
                print(f"加载JSON出错: {str(e)}")

    def update_path_count(self):
        """更新路径数量显示"""
        self.path_count_label.setText(f"路径数量: {len(self.paths)}")

    def save_state(self):
        """保存当前状态到历史记录"""
        self.history.append([path.copy() for path in self.paths])
        self.undo_btn.setEnabled(True)

    def undo(self):
        """撤销操作"""
        if self.history:
            self.paths = self.history.pop()
            self.update_path_count()
            self.draw_preview()
            self.undo_btn.setEnabled(bool(self.history))

    def delete_selected_path(self):
        """删除选中的路径"""
        if self.preview_label.hover_path_index >= 0:
            # 保存当前状态
            self.save_state()
            
            # 删除路径
            del self.paths[self.preview_label.hover_path_index]
            
            # 清除选中状态
            self.preview_label.clear_selection()
            
            # 更新显示
            self.update_path_count()
            self.draw_preview()

    def update_point(self, path_idx, point_idx, x, y):
        """更新路径点坐标"""
        if 0 <= path_idx < len(self.paths) and 0 <= point_idx < len(self.paths[path_idx]):
            self.paths[path_idx][point_idx] = [int(x), int(y)]
            self.draw_preview()

    def save_json(self):
        """保存JSON文件"""
        if not self.paths or not self.image_size:
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存JSON文件",
            "",
            "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                data = {
                    'paths': self.paths,
                    'image_size': self.image_size
                }
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
            except Exception as e:
                print(f"保存JSON出错: {str(e)}")

    def draw_preview(self):
        """绘制预览图"""
        if not self.paths or not self.image_size:
            return
            
        # 创建空白图像
        image = QImage(
            self.image_size[1],
            self.image_size[0],
            QImage.Format_RGB32
        )
        image.fill(Qt.black)
        
        # 创建绘制器
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 设置画笔
        pen = QPen(Qt.white)
        pen.setWidth(2)
        painter.setPen(pen)
        
        # 绘制所有路径
        for path_idx, path in enumerate(self.paths):
            if len(path) < 2:
                continue
                
            # 设置路径颜色（选中的路径用不同颜色）
            if path_idx == self.preview_label.selected_path_index:
                pen.setColor(Qt.cyan)  # 选中的路径用青色
                pen.setWidth(3)
            else:
                pen.setColor(Qt.white)  # 普通路径用白色
                pen.setWidth(2)
            painter.setPen(pen)
            
            # 绘制路径线段
            for i in range(len(path) - 1):
                start = QPoint(*path[i])
                end = QPoint(*path[i + 1])
                painter.drawLine(start, end)
            
            # 在路径中间位置显示编号
            mid_point = path[len(path) // 2]
            pen.setColor(Qt.yellow)
            painter.setPen(pen)
            painter.drawText(
                QPoint(*mid_point) + QPoint(5, 5),
                str(path_idx + 1)
            )
        
        # 单独绘制所有端点
        for path in self.paths:
            if not path:
                continue
                
            # 绘制起点（绿色）
            pen.setColor(Qt.green)
            pen.setWidth(8)  # 增大端点大小
            painter.setPen(pen)
            painter.drawPoint(QPoint(*path[0]))
            
            # 绘制终点（红色）
            pen.setColor(Qt.red)
            painter.setPen(pen)
            painter.drawPoint(QPoint(*path[-1]))
        
        # 绘制悬停和选中效果
        if self.preview_label.hover_point is not None:
            pen.setColor(Qt.yellow)
            pen.setWidth(10)  # 增大高亮效果
            painter.setPen(pen)
            painter.drawPoint(self.preview_label.hover_point)
        
        if self.preview_label.selected_point is not None:
            pen.setColor(Qt.cyan)
            pen.setWidth(10)
            painter.setPen(pen)
            painter.drawPoint(self.preview_label.selected_point)
        
        painter.end()
        
        # 显示预览图
        pixmap = QPixmap.fromImage(image)
        self.preview_label.setPixmap(pixmap)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PathPreview()
    window.show()
    sys.exit(app.exec_()) 