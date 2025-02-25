import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

class ExportThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)
    
    def __init__(self, animator, filename, speed):
        super().__init__()
        self.animator = animator
        self.filename = filename
        self.speed = speed
        self.is_running = True
    
    def run(self):
        try:
            # 获取图像尺寸
            height, width = self.animator.image_size[:2]
            
            # 根据文件扩展名选择导出格式
            is_gif = self.filename.lower().endswith('.gif')
            
            # 收集所有帧
            frames = []
            total_frames = len(self.animator.paths) * self.animator.total_frames
            current_frame = 0
            
            # 重置动画状态
            self.animator.reset()
            
            while current_frame < total_frames and self.is_running:
                # 获取当前帧
                frame = self.animator._draw_frame()  # 直接使用返回值
                frames.append(frame)
                
                # 更新动画状态
                self.animator.current_frame += 1
                if self.animator.current_frame >= self.animator.total_frames:
                    self.animator.current_frame = 0
                    self.animator.current_path_index += 1
                
                current_frame += 1
                self.progress.emit(int(current_frame * 100 / total_frames))
            
            if not self.is_running:
                return
            
            if is_gif:
                # 导出GIF
                import imageio
                imageio.mimsave(
                    self.filename,
                    frames,
                    fps=int(30 * self.speed)
                )
            else:
                # 导出MP4
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(
                    self.filename,
                    fourcc,
                    30 * self.speed,  # FPS
                    (width, height)
                )
                
                # 写入所有帧
                for frame in frames:
                    # 转换为BGR格式
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    out.write(frame_bgr)
                
                out.release()
            
            self.finished.emit(True)
            
        except Exception as e:
            print(f"导出错误: {str(e)}")  # 添加错误打印
            self.error.emit(str(e))
            self.finished.emit(False)
        finally:
            # 重置动画状态
            self.animator.reset()
    
    def stop(self):
        self.is_running = False
        self.wait()  # 等待线程完成 