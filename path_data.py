import json
import numpy as np

class PathData:
    def __init__(self):
        self.paths = []
        self.endpoints = []
        self.crosspoints = []
        self.fitted_paths = []
        self.image_size = None
        self._validate_cache = {}  # 添加验证缓存
    
    def add_path_data(self, paths, endpoints, crosspoints, image_size):
        """添加路径数据"""
        self.paths = paths
        self.endpoints = endpoints
        self.crosspoints = crosspoints
        self.image_size = image_size
    
    def add_fitted_paths(self, fitted_paths):
        """添加拟合路径数据"""
        self.fitted_paths = fitted_paths
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'image_size': self.image_size,
            'paths': [[(int(x), int(y)) for x, y in path] for path in self.paths],
            'endpoints': [(int(x), int(y)) for x, y in self.endpoints],
            'crosspoints': [(int(x), int(y)) for x, y in self.crosspoints],
            'fitted_paths': [
                {
                    'type': path_type,
                    'points': [(int(x), int(y)) for x, y in points]
                }
                for path_type, points in self.fitted_paths
            ]
        }
    
    def from_dict(self, data):
        """从字典格式加载数据"""
        self.image_size = tuple(data['image_size'])
        self.paths = [[(x, y) for x, y in path] for path in data['paths']]
        self.endpoints = [(x, y) for x, y in data['endpoints']]
        self.crosspoints = [(x, y) for x, y in data['crosspoints']]
        self.fitted_paths = [
            (path['type'], [(x, y) for x, y in path['points']])
            for path in data['fitted_paths']
        ]
    
    def save_to_file(self, filename):
        """保存到JSON文件"""
        try:
            data = self.to_dict()
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存文件时出错: {str(e)}")
            return False
    
    def load_from_file(self, filename):
        """从JSON文件加载"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.from_dict(data)
            return True
        except Exception as e:
            print(f"加载文件时出错: {str(e)}")
            return False
    
    def validate_path_data(self):
        """优化验证性能"""
        cache_key = (
            tuple(map(tuple, self.paths)), 
            tuple(self.endpoints),
            tuple(self.crosspoints),
            self.image_size
        )
        
        if cache_key in self._validate_cache:
            return self._validate_cache[cache_key]
            
        result = self._do_validate()
        self._validate_cache[cache_key] = result
        return result
    
    def _do_validate(self):
        """实际的验证逻辑"""
        try:
            if not self.paths or not isinstance(self.paths, list):
                return False
            
            if not self.image_size or len(self.image_size) != 3:
                return False
            
            # 检查路径点的有效性
            for path in self.paths:
                if not path or len(path) < 2:
                    return False
                for point in path:
                    if not isinstance(point, tuple) or len(point) != 2:
                        return False
                    x, y = point
                    if x < 0 or y < 0 or x >= self.image_size[1] or y >= self.image_size[0]:
                        return False
            
            return True
        except Exception as e:
            print(f"路径数据验证出错: {str(e)}")
            return False 