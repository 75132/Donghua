import cv2
import numpy as np
from skimage.morphology import skeletonize as sk_skeletonize
from skimage.morphology import thin
from skimage.graph import route_through_array
from skimage import img_as_float, img_as_ubyte
from scipy.spatial.distance import cdist
from scipy.spatial import cKDTree
from scipy.sparse.csgraph import connected_components
from scipy.sparse import csr_matrix

class ImageProcessor:
    def __init__(self):
        self.cache = {}  # 添加缓存机制
    
    def load_image(self, file_path):
        """加载图像文件"""
        try:
            image = cv2.imread(file_path)
            if image is None:
                print("无法加载图像文件")
                return None
            # 转换为RGB格式以便显示
            return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        except Exception as e:
            print(f"加载图像时出错: {str(e)}")
            return None
    
    def preprocess(self, image, threshold=127, noise_kernel_size=3):
        """优化预处理性能"""
        cache_key = (id(image), threshold, noise_kernel_size)
        if cache_key in self.cache:
            return self.cache[cache_key]
            
        result = self._do_preprocess(image, threshold, noise_kernel_size)
        self.cache[cache_key] = result
        return result
    
    def _do_preprocess(self, image, threshold, noise_kernel_size):
        """实际的预处理逻辑"""
        try:
            # 转换为灰度图
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            
            # 使用全局阈值进行二值化
            _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
            
            # 进行形态学操作去除噪点
            kernel = np.ones((noise_kernel_size, noise_kernel_size), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            
            # 转回RGB格式以便显示
            return cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
            
        except Exception as e:
            print(f"预处理图像时出错: {str(e)}")
            return image 

    def zhang_suen_thinning(self, binary_image):
        """
        实现Zhang-Suen细化算法
        输入：二值图像（黑底白前景）
        输出：细化后的图像
        """
        def neighbors(x, y, image):
            """获取8邻域像素值"""
            return [image[x-1, y], image[x-1, y+1],
                    image[x, y+1], image[x+1, y+1],
                    image[x+1, y], image[x+1, y-1],
                    image[x, y-1], image[x-1, y-1]]

        def transitions(neighbors):
            """计算黑白转换次数"""
            n = neighbors + neighbors[0:1]
            return sum((n1, n2) == (0, 1) for n1, n2 in zip(n, n[1:]))

        if len(binary_image.shape) > 2:
            binary_image = cv2.cvtColor(binary_image, cv2.COLOR_RGB2GRAY)
        
        # 确保图像是二值图像
        binary_image = binary_image > 127
        binary_image = binary_image.astype(np.uint8) * 255
        
        image = binary_image.copy() / 255
        changing = True
        iteration = 0
        
        while changing and iteration < 100:  # 限制最大迭代次数
            changing = False
            iteration += 1
            
            # 第一子迭代
            deletion_markers = []
            for i in range(1, image.shape[0]-1):
                for j in range(1, image.shape[1]-1):
                    if image[i, j] == 1:  # 白色前景像素
                        P = neighbors(i, j, image)
                        if (2 <= sum(P) <= 6 and  # 条件1
                            transitions(P) == 1 and  # 条件2
                            P[0] * P[2] * P[4] == 0 and  # 条件3
                            P[2] * P[4] * P[6] == 0):  # 条件4
                            deletion_markers.append((i, j))
            
            # 执行删除
            for i, j in deletion_markers:
                image[i, j] = 0
                changing = True
            
            # 第二子迭代
            deletion_markers = []
            for i in range(1, image.shape[0]-1):
                for j in range(1, image.shape[1]-1):
                    if image[i, j] == 1:
                        P = neighbors(i, j, image)
                        if (2 <= sum(P) <= 6 and
                            transitions(P) == 1 and
                            P[0] * P[2] * P[6] == 0 and  # 条件3'
                            P[0] * P[4] * P[6] == 0):  # 条件4'
                            deletion_markers.append((i, j))
            
            # 执行删除
            for i, j in deletion_markers:
                image[i, j] = 0
                changing = True
        
        return (image * 255).astype(np.uint8)

    def skeletonize(self, image):
        """骨架提取主函数"""
        try:
            # 确保图像是二值图
            if len(image.shape) > 2:
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            else:
                gray = image
            
            # 二值化（如果还没有二值化）
            if np.max(gray) > 1:
                _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            else:
                binary = gray
            
            # 应用Zhang-Suen细化
            skeleton = self.zhang_suen_thinning(binary)
            
            # 转回RGB格式以便显示
            return cv2.cvtColor(skeleton, cv2.COLOR_GRAY2RGB)
            
        except Exception as e:
            print(f"骨架提取时出错: {str(e)}")
            return image 

    def extract_paths(self, skeleton_image):
        """提取路径，优化端点检测和路径分割"""
        try:
            # 转换为二值图像
            if len(skeleton_image.shape) > 2:
                binary = cv2.cvtColor(skeleton_image, cv2.COLOR_RGB2GRAY)
            else:
                binary = skeleton_image
            binary = (binary > 127).astype(np.uint8) * 255

            # 获取所有非零点坐标
            points = np.column_stack(np.where(binary > 0)[::-1])
            
            # 初始端点和交叉点检测
            endpoints, crosspoints = self._find_special_points(binary)
            
            # 合并相近的端点（增加距离阈值）
            endpoints = self._merge_close_points(endpoints, distance_threshold=8)
            
            # 合并相近的交叉点
            crosspoints = self._merge_close_points(crosspoints, distance_threshold=5)
            
            # 提取路径
            paths = self._extract_path_segments(binary, endpoints, crosspoints)
            
            # 优化路径：合并可以连接的路径段
            paths = self._optimize_paths(paths)
            
            # 确保路径非空
            if not paths:
                print("未检测到有效路径")
                # 如果没有检测到路径，创建一个包含所有点的路径
                if len(points) > 0:
                    paths = [points.tolist()]
            
            return paths, endpoints, crosspoints
        
        except Exception as e:
            print(f"路径提取出错: {str(e)}")
            return [], [], []

    def _merge_close_points(self, points, distance_threshold):
        """合并距离小于阈值的点"""
        if len(points) < 2:
            return points
        
        # 转换为numpy数组
        points = np.array(points)
        
        # 计算点之间的距离矩阵
        distances = cdist(points, points)
        
        # 创建合并后的点集
        merged_points = []
        used_indices = set()
        
        for i in range(len(points)):
            if i in used_indices:
                continue
            
            # 找到与当前点距离小于阈值的所有点
            close_points_indices = np.where(distances[i] < distance_threshold)[0]
            
            if len(close_points_indices) > 1:
                # 如果有多个相近点，取它们的平均位置
                cluster_points = points[close_points_indices]
                mean_point = np.mean(cluster_points, axis=0)
                merged_points.append(tuple(map(int, mean_point)))
                used_indices.update(close_points_indices)
            else:
                # 如果没有相近点，保留原点
                merged_points.append(tuple(map(int, points[i])))
                used_indices.add(i)
        
        return merged_points

    def _optimize_paths(self, paths):
        """优化路径，合并可以连接的路径段"""
        if len(paths) < 2:
            return paths
        
        optimized_paths = []
        used_paths = set()
        
        for i, path1 in enumerate(paths):
            if i in used_paths:
                continue
            
            current_path = list(path1)
            used_paths.add(i)
            
            # 尝试连接其他路径
            while True:
                found_connection = False
                
                for j, path2 in enumerate(paths):
                    if j in used_paths:
                        continue
                    
                    # 检查路径端点是否接近
                    if self._can_connect_paths(current_path, path2):
                        # 连接路径
                        current_path = self._connect_paths(current_path, path2)
                        used_paths.add(j)
                        found_connection = True
                        break
                
                if not found_connection:
                    break
            
            optimized_paths.append(current_path)
        
        return optimized_paths

    def _can_connect_paths(self, path1, path2, threshold=5):
        """检查两条路径是否可以连接"""
        # 检查首尾端点的距离
        dist1 = np.sqrt(np.sum((np.array(path1[-1]) - np.array(path2[0]))**2))
        dist2 = np.sqrt(np.sum((np.array(path1[-1]) - np.array(path2[-1]))**2))
        dist3 = np.sqrt(np.sum((np.array(path1[0]) - np.array(path2[0]))**2))
        dist4 = np.sqrt(np.sum((np.array(path1[0]) - np.array(path2[-1]))**2))
        
        return min(dist1, dist2, dist3, dist4) < threshold

    def _connect_paths(self, path1, path2):
        """连接两条路径"""
        # 计算所有可能的连接方式的距离
        p1_start, p1_end = np.array(path1[0]), np.array(path1[-1])
        p2_start, p2_end = np.array(path2[0]), np.array(path2[-1])
        
        distances = [
            (np.linalg.norm(p1_end - p2_start), 1),   # path1 -> path2
            (np.linalg.norm(p1_end - p2_end), 2),     # path1 -> reversed(path2)
            (np.linalg.norm(p1_start - p2_start), 3), # reversed(path1) -> path2
            (np.linalg.norm(p1_start - p2_end), 4)    # reversed(path1) -> reversed(path2)
        ]
        
        # 选择最短的连接方式
        _, connection_type = min(distances, key=lambda x: x[0])
        
        if connection_type == 1:
            return path1 + path2
        elif connection_type == 2:
            return path1 + list(reversed(path2))
        elif connection_type == 3:
            return list(reversed(path1)) + path2
        else:
            return list(reversed(path1)) + list(reversed(path2))

    def visualize_paths(self, image_shape, paths, endpoints, crosspoints):
        """可视化路径、端点和交叉点"""
        # 创建彩色图像
        result = np.zeros((*image_shape[:2], 3), dtype=np.uint8)
        
        # 定义一组不同的颜色
        colors = [
            (255, 255, 255),  # 白色
            (255, 255, 0),    # 黄色
            (0, 255, 255),    # 青色
            (255, 0, 255),    # 粉色
            (128, 255, 0),    # 黄绿色
            (0, 255, 128),    # 青绿色
            (128, 128, 255),  # 淡蓝色
            (255, 128, 128),  # 淡红色
            (128, 255, 255),  # 淡青色
            (255, 128, 255),  # 淡粉色
        ]
        
        # 绘制路径（使用不同颜色）
        for i, path in enumerate(paths):
            color = colors[i % len(colors)]  # 循环使用颜色
            # 绘制路径线条
            for j in range(len(path) - 1):
                pt1 = path[j]
                pt2 = path[j + 1]
                cv2.line(result, pt1, pt2, color, 2)  # 增加线条宽度
            # 在路径的起点和终点绘制小圆点
            cv2.circle(result, path[0], 2, color, -1)
            cv2.circle(result, path[-1], 2, color, -1)
        
        # 绘制端点（绿色，稍大一些）
        for point in endpoints:
            cv2.circle(result, point, 4, (0, 255, 0), -1)
            # 添加白色边框使端点更明显
            cv2.circle(result, point, 5, (255, 255, 255), 1)
        
        # 绘制交叉点（红色，稍小一些）
        for point in crosspoints:
            cv2.circle(result, point, 3, (0, 0, 255), -1)
            # 添加白色边框使交叉点更明显
            cv2.circle(result, point, 4, (255, 255, 255), 1)
        
        return result 

    def fit_paths(self, paths, endpoints, crosspoints, line_threshold=0.98, control_dist_factor=0.25):
        """路径拟合主函数"""
        try:
            fitted_paths = []
            for path in paths:
                # 判断路径类型并进行相应拟合
                if self._is_line(path, threshold=line_threshold):
                    fitted_path = self._fit_line(path)
                    fitted_paths.append(('line', fitted_path))
                else:
                    fitted_path = self._fit_bezier(path, control_dist_factor)
                    fitted_paths.append(('bezier', fitted_path))
            
            return fitted_paths
        
        except Exception as e:
            print(f"路径拟合出错: {str(e)}")
            return []

    def _is_line(self, path, threshold=0.98):
        """判断路径是否为直线，提高阈值减少直线判定"""
        if len(path) < 3:
            return True
        
        points = np.array(path)
        # 计算路径的总长度
        total_length = np.sum(np.sqrt(np.sum(np.diff(points, axis=0)**2, axis=1)))
        # 计算起点到终点的直线距离
        end_to_end = np.sqrt(np.sum((points[-1] - points[0])**2))
        
        # 提高阈值，只有非常接近直线的才判定为直线
        return end_to_end / total_length > threshold

    def _fit_line(self, path):
        """拟合直线"""
        points = np.array(path)
        vx, vy, x0, y0 = cv2.fitLine(points, cv2.DIST_L2, 0, 0.01, 0.01)
        
        # 计算直线的两个端点
        t = np.array([0, 1])
        x = x0 + vx * t[:, np.newaxis]
        y = y0 + vy * t[:, np.newaxis]
        
        return [(int(x[0]), int(y[0])), (int(x[1]), int(y[1]))]

    def _fit_bezier(self, path, control_dist_factor=0.25):
        """拟合三次贝塞尔曲线"""
        points = np.array(path)
        n_points = len(points)
        
        if n_points < 4:
            return path
        
        # 选择控制点
        p0 = points[0]  # 起点
        p3 = points[-1]  # 终点
        
        # 计算路径的总长度
        path_length = np.sum(np.sqrt(np.sum(np.diff(points, axis=0)**2, axis=1)))
        
        # 使用传入的控制点距离因子
        control_dist = path_length * control_dist_factor
        
        # 使用更少的点来计算切线方向，减少偏差
        n_points_for_tangent = min(n_points // 6, 5)  # 减少参考点数量
        
        # 计算起点切线
        start_tangent = np.zeros(2)
        for i in range(min(n_points_for_tangent, n_points-1)):
            start_tangent += points[i+1] - points[i]
        if np.linalg.norm(start_tangent) > 0:
            start_tangent = start_tangent / np.linalg.norm(start_tangent)
        
        # 计算终点切线
        end_tangent = np.zeros(2)
        for i in range(max(0, n_points-n_points_for_tangent-1), n_points-1):
            end_tangent += points[i+1] - points[i]
        if np.linalg.norm(end_tangent) > 0:
            end_tangent = end_tangent / np.linalg.norm(end_tangent)
        
        # 计算控制点，减小控制点的影响
        p1 = p0 + start_tangent * control_dist * 0.8  # 减小控制点距离
        p2 = p3 - end_tangent * control_dist * 0.8
        
        return [tuple(map(int, p)) for p in [p0, p1, p2, p3]]

    def visualize_fitted_paths(self, image_shape, fitted_paths, endpoints, crosspoints):
        """可视化拟合后的路径，增加采样点数量"""
        result = np.zeros((*image_shape[:2], 3), dtype=np.uint8)
        
        # 定义颜色
        colors = [
            (255, 255, 255),  # 白色
            (255, 255, 0),    # 黄色
            (0, 255, 255),    # 青色
            (255, 0, 255),    # 粉色
            (128, 255, 0),    # 黄绿色
        ]
        
        # 绘制拟合路径
        for i, (path_type, path) in enumerate(fitted_paths):
            color = colors[i % len(colors)]
            if path_type == 'line':
                # 绘制直线
                cv2.line(result, path[0], path[1], color, 2)
            else:  # bezier
                # 增加采样点数量，使曲线更平滑
                points = np.array(path)
                prev_point = None
                for t in np.linspace(0, 1, 200):  # 增加采样点
                    point = self._bezier_point(points, t)
                    current_point = tuple(map(int, point))
                    
                    if prev_point is not None:
                        cv2.line(result, prev_point, current_point, color, 2)
                    prev_point = current_point
        
        # 绘制端点和交叉点
        for point in endpoints:
            cv2.circle(result, point, 4, (0, 255, 0), -1)
            cv2.circle(result, point, 5, (255, 255, 255), 1)
        
        for point in crosspoints:
            cv2.circle(result, point, 3, (0, 0, 255), -1)
            cv2.circle(result, point, 4, (255, 255, 255), 1)
        
        return result

    def _bezier_point(self, points, t):
        """计算贝塞尔曲线上的点"""
        if len(points) == 1:
            return points[0]
        
        new_points = []
        for i in range(len(points) - 1):
            x = points[i][0] * (1 - t) + points[i + 1][0] * t
            y = points[i][1] * (1 - t) + points[i + 1][1] * t
            new_points.append((x, y))
        
        return self._bezier_point(new_points, t)

    def _find_special_points(self, binary):
        """查找端点和交叉点"""
        # 获取所有非零点坐标
        points = np.column_stack(np.where(binary > 0)[::-1])
        
        endpoints = []
        crosspoints = []
        
        # 定义8邻域的偏移量
        neighbors = [(-1,-1), (-1,0), (-1,1),
                    (0,-1),          (0,1),
                    (1,-1),  (1,0),  (1,1)]
        
        height, width = binary.shape
        
        # 检查每个白色像素点
        for x, y in points:
            # 统计8邻域内的白色像素数量
            neighbor_count = 0
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if (0 <= nx < width and 0 <= ny < height and 
                    binary[ny, nx] > 0):
                    neighbor_count += 1
            
            # 根据邻域像素数量判断点的类型
            if neighbor_count == 1:
                endpoints.append((x, y))
            elif neighbor_count > 2:
                crosspoints.append((x, y))
        
        return endpoints, crosspoints

    def _extract_path_segments(self, binary, endpoints, crosspoints):
        """提取路径段"""
        # 创建所有特殊点的集合
        special_points = set(tuple(p) for p in endpoints + crosspoints)
        
        # 获取所有路径点
        path_points = np.column_stack(np.where(binary > 0)[::-1])
        
        # 创建已访问点的集合
        visited = set()
        paths = []
        
        # 定义8邻域的偏移量（按顺时针排序）
        neighbors = [(-1,0), (-1,1), (0,1), (1,1),
                    (1,0), (1,-1), (0,-1), (-1,-1)]
        
        height, width = binary.shape
        
        def get_neighbors(point):
            """获取点的有效邻居（按顺时针顺序）"""
            x, y = point
            valid_neighbors = []
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if (0 <= nx < width and 0 <= ny < height and 
                    binary[ny, nx] > 0 and
                    (nx, ny) not in visited):
                    valid_neighbors.append((nx, ny))
            return valid_neighbors
        
        def trace_path(start_point):
            """从起点追踪路径"""
            current_path = [start_point]
            visited.add(start_point)
            current_point = start_point
            
            while True:
                # 获取当前点的未访问邻居
                next_points = get_neighbors(current_point)
                
                # 如果没有未访问的邻居，结束路径
                if not next_points:
                    break
                
                # 选择最接近当前方向的下一个点
                if len(current_path) > 1:
                    last_dir = np.array(current_point) - np.array(current_path[-2])
                    next_dirs = [np.array(p) - np.array(current_point) for p in next_points]
                    angles = [np.arctan2(np.cross(last_dir, d), np.dot(last_dir, d)) for d in next_dirs]
                    next_point = next_points[np.argmin(np.abs(angles))]
                else:
                    next_point = next_points[0]
                
                # 如果下一个点是特殊点，将其添加到路径后结束
                if next_point in special_points and len(current_path) > 1:
                    current_path.append(next_point)
                    visited.add(next_point)
                    break
                
                # 继续路径
                current_path.append(next_point)
                visited.add(next_point)
                current_point = next_point
            
            return current_path
        
        # 从每个端点和交叉点开始追踪路径
        for start_point in special_points:
            if start_point not in visited:
                path = trace_path(start_point)
                if len(path) > 1:
                    paths.append(path)
                # 从这个点开始向所有未访问的邻居追踪
                for neighbor in get_neighbors(start_point):
                    if neighbor not in visited:
                        path = trace_path(start_point)
                        if len(path) > 1:
                            paths.append(path)
        
        # 处理可能的闭合路径
        for point in path_points:
            point = tuple(point)
            if point not in visited:
                path = trace_path(point)
                if len(path) > 1:
                    paths.append(path)
        
        return paths