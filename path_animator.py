import numpy as np
import cv2
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

class PathAnimator(QObject):
    # 动画更新信号
    frame_ready = pyqtSignal(object)
    animation_finished = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.paths = []
        self.endpoints = []
        self.crosspoints = []
        self.image_size = None
        self.speed = 1.0
        self.current_frame = 0
        self.total_frames = 50  # 减少每条路径的帧数，加快播放速度
        self.current_path_index = 0
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._update_animation)
        self.is_playing = False
        self.show_points = False  # 添加控制端点显示的标志
        
    def set_data(self, paths, endpoints, crosspoints, image_size):
        """设置路径数据"""
        self.paths = paths
        self.endpoints = endpoints
        self.crosspoints = crosspoints
        self.image_size = image_size
        self.reset()
    
    def set_speed(self, speed):
        """设置动画速度"""
        self.speed = speed
        if self.is_playing:
            self.animation_timer.setInterval(int(20 / speed))  # 基础间隔改为20ms
    
    def set_show_points(self, show):
        """设置是否显示端点"""
        self.show_points = show
        if not self.is_playing:
            self._draw_frame()
    
    def reset(self):
        """重置动画状态"""
        self.current_frame = 0
        self.current_path_index = 0
        self.is_playing = False
        self.animation_timer.stop()
    
    def play(self):
        """开始播放动画"""
        if not self.paths:
            return
        self.is_playing = True
        self.animation_timer.setInterval(int(20 / self.speed))  # 基础间隔改为20ms
        self.animation_timer.start()
    
    def pause(self):
        """暂停动画"""
        self.is_playing = False
        self.animation_timer.stop()
    
    def stop(self):
        """停止动画"""
        self.reset()
        self._draw_frame()
    
    def _update_animation(self):
        """更新动画帧"""
        if not self.is_playing:
            return
            
        self._draw_frame()
        
        self.current_frame += 1
        if self.current_frame >= self.total_frames:
            self.current_frame = 0
            self.current_path_index += 1
            
            if self.current_path_index >= len(self.paths):
                self.current_path_index = 0
                self.animation_finished.emit()
    
    def _draw_frame(self):
        """绘制当前帧"""
        if not self.image_size:
            return
        
        result = np.zeros((*self.image_size[:2], 3), dtype=np.uint8)
        
        # 首先绘制所有路径的背景
        for path in self.paths:
            for j in range(len(path) - 1):
                cv2.line(result, path[j], path[j+1], (0, 0, 128), 1)  # 减小线宽
        
        # 绘制已完成的路径
        for i in range(self.current_path_index):
            path = self.paths[i]
            for j in range(len(path) - 1):
                cv2.line(result, path[j], path[j+1], (255, 255, 255), 2)
        
        # 绘制当前路径
        if self.current_path_index < len(self.paths):
            path = self.paths[self.current_path_index]
            progress = self.current_frame / self.total_frames
            points = self._interpolate_path(path, progress)
            
            # 绘制当前路径的已完成部分
            for i in range(len(points) - 1):
                cv2.line(result, points[i], points[i+1], (255, 255, 255), 2)
        
        # 只在非播放状态或启用显示时绘制端点和交叉点
        if not self.is_playing or self.show_points:
            for point in self.endpoints:
                cv2.circle(result, point, 3, (0, 255, 0), -1)
            
            for point in self.crosspoints:
                cv2.circle(result, point, 2, (0, 0, 255), -1)
        
        self.frame_ready.emit(result)
    
    def _interpolate_path(self, path, progress):
        """计算路径的插值点"""
        if len(path) < 2:
            return path
            
        total_length = 0
        segment_lengths = []
        
        # 计算路径总长度和每段长度
        for i in range(len(path) - 1):
            length = np.sqrt(np.sum((np.array(path[i+1]) - np.array(path[i]))**2))
            total_length += length
            segment_lengths.append(length)
        
        target_length = total_length * progress
        current_length = 0
        
        # 找到当前位置
        for i, length in enumerate(segment_lengths):
            if current_length + length >= target_length:
                segment_progress = (target_length - current_length) / length
                start = np.array(path[i])
                end = np.array(path[i+1])
                point = start + (end - start) * segment_progress
                return path[:i+1] + [tuple(map(int, point))]
            current_length += length
        
        return path 