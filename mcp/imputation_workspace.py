#!/usr/bin/env python3
"""
基因型填充工作区管理模块
管理工作区创建、文件上传、格式校验和转换
"""

import os
import re
import json
import shutil
import logging
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger('imputation_workspace')


def _default_workspace_dir() -> str:
    """根据本文件位置推断默认工作区目录：repo/agent_framework/data"""
    return str(Path(__file__).resolve().parents[1] / "agent_framework" / "data")


class ImputationWorkspace:
    """
    基因型填充工作区管理类
    
    功能：
    1. 工作区创建和管理
    2. 文件上传和存储
    3. 数据格式校验
    4. 格式转换（PLINK ↔ VCF）
    5. 工作区状态跟踪
    """
    
    def __init__(self, base_dir: str = ""):
        if not base_dir:
            base_dir = _default_workspace_dir()
        """
        初始化工作区管理器
        
        Args:
            base_dir: 工作区根目录
        """
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
        
        # 工作区索引文件
        self.index_file = os.path.join(self.base_dir, 'workspaces.json')
        self._workspaces = self._load_index()
    
    def _load_index(self) -> Dict[str, Any]:
        """加载工作区索引"""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载工作区索引失败: {e}")
        return {}
    
    def _save_index(self):
        """保存工作区索引"""
        try:
            with open(self.index_file, 'w') as f:
                json.dump(self._workspaces, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存工作区索引失败: {e}")
    
    def create_workspace(self, output_path: Optional[str] = None, 
                        description: Optional[str] = None) -> Dict[str, Any]:
        """
        创建新工作区
        
        Args:
            output_path: 用户指定的输出路径（可选）
            description: 工作区描述
            
        Returns:
            工作区信息字典
        """
        workspace_id = 'ws_' + datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 确定工作区路径
        if output_path and os.path.isdir(output_path):
            workspace_dir = os.path.join(output_path, f'imputation_workspace_{workspace_id}')
        else:
            workspace_dir = os.path.join(self.base_dir, workspace_id)
        
        # 创建工作区目录结构
        dirs = {
            'root': workspace_dir,
            'input': os.path.join(workspace_dir, 'input'),
            'converted': os.path.join(workspace_dir, 'converted'),
            'output': os.path.join(workspace_dir, 'output'),
            'logs': os.path.join(workspace_dir, 'logs'),
            'temp': os.path.join(workspace_dir, 'temp')
        }
        
        for dir_path in dirs.values():
            os.makedirs(dir_path, exist_ok=True)
        
        workspace_info = {
            'workspace_id': workspace_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'description': description,
            'directories': dirs,
            'status': 'created',
            'files': {
                'input': [],
                'converted': [],
                'output': []
            },
            'validation_results': {},
            'conversion_results': {},
            'imputation_results': {}
        }
        
        self._workspaces[workspace_id] = workspace_info
        self._save_index()
        
        logger.info(f"创建工作区: {workspace_id}")
        return workspace_info
    
    def get_workspace(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        """获取工作区信息"""
        return self._workspaces.get(workspace_id)
    
    def list_workspaces(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出所有工作区"""
        workspaces = sorted(
            self._workspaces.values(),
            key=lambda x: x['created_at'],
            reverse=True
        )
        return workspaces[:limit]
    
    def delete_workspace(self, workspace_id: str) -> bool:
        """删除工作区"""
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            return False
        
        try:
            # 删除目录
            shutil.rmtree(workspace['directories']['root'], ignore_errors=True)
            # 从索引中移除
            del self._workspaces[workspace_id]
            self._save_index()
            logger.info(f"删除工作区: {workspace_id}")
            return True
        except Exception as e:
            logger.error(f"删除工作区失败: {e}")
            return False
    
    def save_uploaded_file(self, workspace_id: str, file_content: bytes, 
                          filename: str) -> Dict[str, Any]:
        """
        保存上传的文件到工作区
        
        Args:
            workspace_id: 工作区ID
            file_content: 文件二进制内容
            filename: 原始文件名
            
        Returns:
            保存结果字典
        """
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            return {'success': False, 'error': '工作区不存在'}
        
        # 安全检查文件名
        safe_filename = os.path.basename(filename)
        if not safe_filename or '..' in safe_filename:
            return {'success': False, 'error': '非法文件名'}
        
        input_dir = workspace['directories']['input']
        file_path = os.path.join(input_dir, safe_filename)
        
        try:
            # 保存文件
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            file_info = {
                'filename': safe_filename,
                'path': file_path,
                'size_bytes': len(file_content),
                'size_mb': round(len(file_content) / (1024 * 1024), 2),
                'uploaded_at': datetime.now(timezone.utc).isoformat(),
                'md5': hashlib.md5(file_content).hexdigest()
            }
            
            # 更新工作区文件列表
            workspace['files']['input'].append(file_info)
            self._save_index()
            
            logger.info(f"保存文件到工作区 {workspace_id}: {safe_filename}")
            return {'success': True, 'file_info': file_info}
            
        except Exception as e:
            logger.error(f"保存文件失败: {e}")
            return {'success': False, 'error': str(e)}
    
    def validate_input_files(self, workspace_id: str) -> Dict[str, Any]:
        """
        校验工作区中的输入文件（扫描真实文件系统）

        Args:
            workspace_id: 工作区ID

        Returns:
            校验结果字典
        """
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            return {'success': False, 'error': '工作区不存在'}

        input_dir = workspace['directories']['input']
        if not os.path.isdir(input_dir):
            return {'success': False, 'error': '输入目录不存在'}

        real_files = []
        try:
            for fname in os.listdir(input_dir):
                fpath = os.path.join(input_dir, fname)
                if os.path.isfile(fpath):
                    real_files.append({'filename': fname, 'path': fpath})
        except Exception as e:
            return {'success': False, 'error': f'读取输入目录失败: {e}'}

        if not real_files:
            return {'success': False, 'error': '没有输入文件'}

        validation_results = {
            'total_files': len(real_files),
            'valid_files': 0,
            'invalid_files': 0,
            'details': []
        }

        vcf_files = []
        plink_files = {'bed': None, 'bim': None, 'fam': None}

        for file_info in real_files:
            filename = file_info['filename']
            filepath = file_info['path']

            result = {
                'filename': filename,
                'valid': False,
                'format': None,
                'errors': []
            }

            if filename.endswith('.vcf.gz') or filename.endswith('.vcf'):
                result['format'] = 'vcf'
                vcf_files.append(filepath)
                vcf_validation = self._validate_vcf_file(filepath)
                result.update(vcf_validation)

            elif filename.endswith('.bed'):
                result['format'] = 'plink_bed'
                plink_files['bed'] = filepath
                result['valid'] = True

            elif filename.endswith('.bim'):
                result['format'] = 'plink_bim'
                plink_files['bim'] = filepath
                result['valid'] = True

            elif filename.endswith('.fam'):
                result['format'] = 'plink_fam'
                plink_files['fam'] = filepath
                result['valid'] = True

            else:
                result['errors'].append('不支持的文件格式')

            if result['valid']:
                validation_results['valid_files'] += 1
            else:
                validation_results['invalid_files'] += 1

            validation_results['details'].append(result)

        if any(plink_files.values()):
            missing = [k for k, v in plink_files.items() if v is None]
            if missing:
                for detail in validation_results['details']:
                    if detail['format'] and detail['format'].startswith('plink'):
                        detail['valid'] = False
                        detail['errors'].append(f"缺少PLINK配套文件: {', '.join(missing)}")
                validation_results['plink_complete'] = False
                validation_results['plink_missing'] = missing
            else:
                validation_results['plink_complete'] = True
                validation_results['plink_files'] = plink_files

        validation_results['has_vcf'] = len(vcf_files) > 0
        validation_results['has_plink'] = plink_files['bed'] is not None

        workspace['validation_results'] = validation_results
        workspace['status'] = 'validated'
        self._save_index()

        return {'success': True, 'validation': validation_results}
    
    def _validate_vcf_file(self, vcf_path: str) -> Dict[str, Any]:
        """详细校验VCF文件"""
        result = {
            'valid': False,
            'is_gzipped': vcf_path.endswith('.gz'),
            'has_index': False,
            'sample_count': 0,
            'variant_count': 0,
            'errors': []
        }
        
        # 检查索引文件
        if result['is_gzipped']:
            result['has_index'] = os.path.exists(f"{vcf_path}.tbi") or \
                                  os.path.exists(f"{vcf_path}.csi")
        
        # 使用bcftools校验
        try:
            # 检查头部
            header_output = subprocess.run(
                ['bcftools', 'view', '-h', vcf_path],
                capture_output=True, text=True, timeout=30
            )
            if header_output.returncode != 0:
                result['errors'].append('VCF头部解析失败')
                return result
            
            # 获取样本数
            samples_output = subprocess.run(
                ['bcftools', 'query', '-l', vcf_path],
                capture_output=True, text=True, timeout=30
            )
            if samples_output.returncode == 0:
                samples = [s for s in samples_output.stdout.strip().split('\n') if s]
                result['sample_count'] = len(samples)
                if len(samples) == 0:
                    result['errors'].append('VCF中没有样本')
            
            # 获取变异数
            if result['has_index']:
                count_output = subprocess.run(
                    ['bcftools', 'index', '-n', vcf_path],
                    capture_output=True, text=True, timeout=30
                )
                if count_output.returncode == 0:
                    result['variant_count'] = int(count_output.stdout.strip())
            
            # 基本校验通过
            if not result['errors']:
                result['valid'] = True
                
        except subprocess.TimeoutExpired:
            result['errors'].append('VCF校验超时')
        except Exception as e:
            result['errors'].append(f'校验失败: {str(e)}')
        
        return result
    
    def convert_plink_to_vcf(self, workspace_id: str, 
                            output_name: Optional[str] = None) -> Dict[str, Any]:
        """
        将PLINK格式转换为VCF
        
        Args:
            workspace_id: 工作区ID
            output_name: 输出文件名（不含扩展名）
            
        Returns:
            转换结果字典
        """
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            return {'success': False, 'error': '工作区不存在'}
        
        validation = workspace.get('validation_results', {})
        if not validation.get('plink_complete'):
            return {'success': False, 'error': 'PLINK文件不完整，无法转换'}
        
        plink_files = validation.get('plink_files', {})
        bed_file = plink_files.get('bed')
        
        if not bed_file:
            return {'success': False, 'error': '找不到BED文件'}
        
        # 生成输出路径
        if output_name is None:
            output_name = f"converted_{workspace_id}"
        
        converted_dir = workspace['directories']['converted']
        output_vcf = os.path.join(converted_dir, f"{output_name}.vcf.gz")
        
        # 构建plink命令
        prefix = bed_file.replace('.bed', '')
        cmd = [
            'plink',
            '--bfile', prefix,
            '--recode', 'vcf',
            'bgz',
            '--out', os.path.join(converted_dir, output_name)
        ]
        
        try:
            logger.info(f"转换PLINK到VCF: {prefix} -> {output_vcf}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1小时超时
            )
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f'转换失败: {result.stderr}',
                    'command': ' '.join(cmd)
                }
            
            # 创建索引
            subprocess.run(
                ['bcftools', 'index', '-t', output_vcf],
                capture_output=True,
                timeout=300
            )
            
            # 验证转换后的文件
            vcf_validation = self._validate_vcf_file(output_vcf)
            
            conversion_result = {
                'success': True,
                'input_format': 'plink',
                'output_format': 'vcf',
                'output_path': output_vcf,
                'command': ' '.join(cmd),
                'validation': vcf_validation
            }
            
            # 更新工作区
            workspace['conversion_results'] = conversion_result
            workspace['files']['converted'].append({
                'filename': f"{output_name}.vcf.gz",
                'path': output_vcf,
                'created_at': datetime.now(timezone.utc).isoformat()
            })
            self._save_index()
            
            return conversion_result
            
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': '转换超时'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_input_for_imputation(self, workspace_id: str) -> Dict[str, Any]:
        """
        获取用于填充的输入文件路径

        扫描真实文件系统，优先返回VCF文件，如果没有则返回转换后的VCF

        Args:
            workspace_id: 工作区ID

        Returns:
            输入文件信息
        """
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            return {'success': False, 'error': '工作区不存在'}

        input_dir = workspace['directories']['input']
        if not os.path.isdir(input_dir):
            return {'success': False, 'error': f'工作区目录不存在: {input_dir}'}

        vcf_files = []
        try:
            for fname in os.listdir(input_dir):
                fpath = os.path.join(input_dir, fname)
                if os.path.isfile(fpath):
                    if fname.endswith('.vcf.gz') or fname.endswith('.vcf'):
                        vcf_files.append({'path': fpath, 'filename': fname})
        except Exception as e:
            return {'success': False, 'error': f'读取输入目录失败: {e}'}

        if vcf_files:
            return {
                'success': True,
                'type': 'original_vcf',
                'path': vcf_files[0]['path'],
                'filename': vcf_files[0]['filename']
            }

        converted_dir = workspace['directories'].get('converted')
        if converted_dir and os.path.isdir(converted_dir):
            try:
                for fname in os.listdir(converted_dir):
                    fpath = os.path.join(converted_dir, fname)
                    if os.path.isfile(fpath) and fname.endswith('.vcf.gz'):
                        return {
                            'success': True,
                            'type': 'converted_vcf',
                            'path': fpath,
                            'filename': fname
                        }
            except Exception:
                pass

        return {'success': False, 'error': '没有可用的VCF输入文件'}
    
    def update_imputation_result(self, workspace_id: str, 
                                 result: Dict[str, Any]) -> bool:
        """更新填充结果到工作区"""
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            return False
        
        workspace['imputation_results'] = result
        workspace['status'] = 'completed' if result.get('success') else 'failed'
        
        # 添加输出文件信息
        for output_file in result.get('output_files', []):
            workspace['files']['output'].append({
                'filename': output_file['filename'],
                'path': output_file['path'],
                'size_mb': output_file.get('size_mb', 0),
                'created_at': datetime.now(timezone.utc).isoformat()
            })
        
        self._save_index()
        return True


# 全局工作区管理器实例
_workspace_manager = None

def get_workspace_manager() -> ImputationWorkspace:
    """获取全局工作区管理器实例"""
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = ImputationWorkspace()
    return _workspace_manager
