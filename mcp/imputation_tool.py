#!/usr/bin/env python3
"""
基因型填充 (Genotype Imputation) 工具模块
使用 beagle 进行 VCF 文件的基因型填充
"""

import os
import re
import subprocess
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger('imputation_tool')


class ImputationTool:
    """
    基因型填充工具类
    
    功能：
    1. 管理参考面板（refpanel）
    2. 执行 beagle 基因型填充
    3. 跟踪任务状态和结果
    """
    
    def __init__(self, refpanel_dir: str = '../refpanel', output_dir: str = '../logs/imputation'):
        """
        初始化填充工具
        
        Args:
            refpanel_dir: 参考面板目录路径
            output_dir: 输出结果目录路径
        """
        self.refpanel_dir = os.path.abspath(refpanel_dir)
        self.output_dir = os.path.abspath(output_dir)
        self.uploads_dir = os.path.join(os.path.dirname(output_dir), 'uploads')
        
        # 确保目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.uploads_dir, exist_ok=True)
        
        # 检查 beagle 是否可用
        self.beagle_path = self._find_beagle()
        
    def _find_beagle(self) -> Optional[str]:
        """查找 beagle 可执行文件"""
        # 首先检查环境变量
        beagle_env = os.environ.get('BEAGLE_PATH')
        if beagle_env and os.path.isfile(beagle_env):
            return beagle_env
            
        # 检查 PATH 中的 beagle
        beagle_cmd = shutil.which('beagle')
        if beagle_cmd:
            return beagle_cmd
            
        # 检查常见路径
        common_paths = [
            '/usr/local/bin/beagle',
            '/usr/bin/beagle',
            os.path.expanduser('~/bin/beagle'),
        ]
        for path in common_paths:
            if os.path.isfile(path):
                return path
                
        logger.warning("未找到 beagle 可执行文件，请设置 BEAGLE_PATH 环境变量或将 beagle 添加到 PATH")
        return None
    
    def get_available_panels(self) -> List[Dict[str, Any]]:
        """
        获取可用的参考面板列表
        
        Returns:
            参考面板信息列表
        """
        panels = []
        
        if not os.path.isdir(self.refpanel_dir):
            logger.warning(f"参考面板目录不存在: {self.refpanel_dir}")
            return panels
        
        # 扫描参考面板目录中的 VCF 文件
        for filename in os.listdir(self.refpanel_dir):
            if filename.endswith('.vcf.gz'):
                panel_path = os.path.join(self.refpanel_dir, filename)
                
                # 检查是否有对应的索引文件
                has_index = os.path.exists(f"{panel_path}.tbi") or os.path.exists(f"{panel_path}.csi")
                
                # 获取文件信息
                stat = os.stat(panel_path)
                
                panel_info = {
                    'name': filename.replace('.vcf.gz', ''),
                    'filename': filename,
                    'path': panel_path,
                    'has_index': has_index,
                    'size_mb': round(stat.st_size / (1024 * 1024), 2),
                    'created_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
                panels.append(panel_info)
        
        # 按文件名排序
        panels.sort(key=lambda x: x['name'])
        return panels
    
    def validate_vcf(self, vcf_path: str) -> Dict[str, Any]:
        """
        验证 VCF 文件格式
        
        Args:
            vcf_path: VCF 文件路径
            
        Returns:
            验证结果字典
        """
        result = {
            'valid': False,
            'exists': False,
            'is_gzipped': False,
            'has_index': False,
            'sample_count': 0,
            'variant_count': 0,
            'error': None
        }
        
        if not os.path.exists(vcf_path):
            result['error'] = f"文件不存在: {vcf_path}"
            return result
        
        result['exists'] = True
        result['is_gzipped'] = vcf_path.endswith('.gz')
        
        # 检查索引文件
        if result['is_gzipped']:
            result['has_index'] = os.path.exists(f"{vcf_path}.tbi") or os.path.exists(f"{vcf_path}.csi")
        
        # 尝试使用 bcftools 获取统计信息
        try:
            # 获取样本数
            samples_output = subprocess.run(
                ['bcftools', 'query', '-l', vcf_path],
                capture_output=True, text=True, timeout=30
            )
            if samples_output.returncode == 0:
                samples = [s for s in samples_output.stdout.strip().split('\n') if s]
                result['sample_count'] = len(samples)
            
            # 获取变异数
            stats_output = subprocess.run(
                ['bcftools', 'index', '-n', vcf_path],
                capture_output=True, text=True, timeout=30
            )
            if stats_output.returncode == 0:
                result['variant_count'] = int(stats_output.stdout.strip())
            else:
                # 如果没有索引，尝试粗略统计
                count_output = subprocess.run(
                    ['bcftools', 'view', '-H', vcf_path, '|', 'wc', '-l'],
                    capture_output=True, text=True, timeout=60, shell=True
                )
                if count_output.returncode == 0:
                    result['variant_count'] = int(count_output.stdout.strip())
            
            result['valid'] = True
            
        except subprocess.TimeoutExpired:
            result['error'] = "验证超时，文件可能过大"
        except Exception as e:
            result['error'] = f"验证失败: {str(e)}"
        
        return result
    
    def run_imputation(
        self,
        input_vcf: str,
        ref_panel: str,
        output_name: Optional[str] = None,
        nthreads: int = 50,
        window: int = 10,  # cM单位 (Beagle 5.x)
        overlap: int = 2,  # cM单位
        imputation_options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行基因型填充
        
        Args:
            input_vcf: 输入 VCF 文件路径（需填充的样本）
            ref_panel: 参考面板文件名（必须在 refpanel 目录中）
            output_name: 输出文件名（不含扩展名）
            nthreads: 线程数
            window: 填充窗口大小（cM，Beagle 5.x 使用 cM 而非 bp）
            overlap: 窗口重叠大小（cM）
            imputation_options: 额外的 beagle 参数
            
        Returns:
            填充结果字典
        """
        start_time = datetime.now(timezone.utc)
        
        result = {
            'success': False,
            'task_id': None,
            'input_file': input_vcf,
            'ref_panel': ref_panel,
            'output_files': [],
            'started_at': start_time.isoformat(),
            'finished_at': None,
            'duration_seconds': 0,
            'command': None,
            'stdout': '',
            'stderr': '',
            'error': None,
            'stats': {}
        }
        
        # 检查 beagle 可用性
        if not self.beagle_path:
            result['error'] = "beagle 未安装或不可访问，请设置 BEAGLE_PATH 环境变量"
            return result
        
        # 验证输入文件
        if not os.path.exists(input_vcf):
            result['error'] = f"输入文件不存在: {input_vcf}"
            return result
        
        # 验证参考面板
        ref_path = os.path.join(self.refpanel_dir, ref_panel)
        if not os.path.exists(ref_path):
            available = [p['filename'] for p in self.get_available_panels()]
            result['error'] = f"参考面板不存在: {ref_panel}. 可用面板: {available}"
            return result
        
        # 生成输出路径
        if output_name is None:
            # 从输入文件名自动生成
            base_name = os.path.basename(input_vcf)
            base_name = re.sub(r'\.vcf(\.gz)?$', '', base_name)
            output_name = f"{base_name}_imputed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        output_prefix = os.path.join(self.output_dir, output_name)
        
        # 构建 beagle 命令
        # 格式: beagle ref=${ref} gt=${input} out=${output} nthreads=${nthreads}
        cmd = [
            self.beagle_path,
            "-Xmx32g",  # 增加 Java 内存到 32GB
            f"ref={ref_path}",
            f"gt={input_vcf}",
            f"out={output_prefix}",
            f"nthreads={nthreads}",
            f"window={window}",
            f"overlap={overlap}",
        ]
        
        # 添加额外选项
        if imputation_options:
            for key, value in imputation_options.items():
                cmd.append(f"{key}={value}")
        
        result['command'] = ' '.join(cmd)
        logger.info(f"开始执行填充: {result['command']}")
        
        try:
            # 执行 beagle
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600 * 4  # 4小时超时
            )
            
            result['stdout'] = process.stdout
            result['stderr'] = process.stderr
            result['return_code'] = process.returncode
            
            if process.returncode == 0:
                result['success'] = True
                
                # 查找输出文件
                expected_outputs = [
                    f"{output_prefix}.vcf.gz",
                    f"{output_prefix}.log",
                ]
                for outfile in expected_outputs:
                    if os.path.exists(outfile):
                        result['output_files'].append({
                            'path': outfile,
                            'filename': os.path.basename(outfile),
                            'size_mb': round(os.path.getsize(outfile) / (1024 * 1024), 2)
                        })
                
                # 尝试生成索引
                vcf_output = f"{output_prefix}.vcf.gz"
                if os.path.exists(vcf_output):
                    try:
                        subprocess.run(
                            ['bcftools', 'index', '-t', vcf_output, '--threads', '4'],
                            capture_output=True, timeout=300
                        )
                        tbi_file = f"{vcf_output}.tbi"
                        if os.path.exists(tbi_file):
                            result['output_files'].append({
                                'path': tbi_file,
                                'filename': os.path.basename(tbi_file),
                                'size_mb': round(os.path.getsize(tbi_file) / (1024 * 1024), 3)
                            })
                    except Exception as e:
                        logger.warning(f"生成索引失败: {e}")
                
                # 收集统计信息
                result['stats'] = self._collect_stats(vcf_output)
                
            else:
                result['error'] = f"beagle 返回非零退出码: {process.returncode}"
                
        except subprocess.TimeoutExpired:
            result['error'] = "填充任务超时（超过4小时）"
        except Exception as e:
            result['error'] = f"执行失败: {str(e)}"
        
        end_time = datetime.now(timezone.utc)
        result['finished_at'] = end_time.isoformat()
        result['duration_seconds'] = round((end_time - start_time).total_seconds(), 2)
        
        return result
    
    def _collect_stats(self, vcf_path: str) -> Dict[str, Any]:
        """收集填充结果的统计信息"""
        stats = {
            'sample_count': 0,
            'variant_count': 0,
            'avg_imputation_accuracy': None
        }
        
        if not os.path.exists(vcf_path):
            return stats
        
        try:
            # 获取样本数
            samples_output = subprocess.run(
                ['bcftools', 'query', '-l', vcf_path],
                capture_output=True, text=True, timeout=30
            )
            if samples_output.returncode == 0:
                samples = [s for s in samples_output.stdout.strip().split('\n') if s]
                stats['sample_count'] = len(samples)
            
            # 获取变异数
            count_output = subprocess.run(
                ['bcftools', 'index', '-n', vcf_path],
                capture_output=True, text=True, timeout=30
            )
            if count_output.returncode == 0:
                stats['variant_count'] = int(count_output.stdout.strip())
                
        except Exception as e:
            logger.warning(f"收集统计信息失败: {e}")
        
        return stats
    
    def get_imputation_status(self, task_id: str) -> Dict[str, Any]:
        """
        获取填充任务状态
        
        注意：实际状态管理由 AsyncTaskManager 处理，
        这里仅提供结果文件的查询
        """
        # 在输出目录中查找匹配的任务结果
        pattern = f"*{task_id}*"
        matching_files = list(Path(self.output_dir).glob(pattern))
        
        if not matching_files:
            return {'found': False, 'task_id': task_id}
        
        return {
            'found': True,
            'task_id': task_id,
            'files': [
                {
                    'filename': f.name,
                    'path': str(f),
                    'size_mb': round(f.stat().st_size / (1024 * 1024), 2),
                    'modified_at': datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
                }
                for f in matching_files
            ]
        }
    
    def save_uploaded_file(self, file_content: bytes, original_filename: str, task_id: str) -> str:
        """
        保存上传的文件
        
        Args:
            file_content: 文件二进制内容
            original_filename: 原始文件名
            task_id: 任务ID
            
        Returns:
            保存后的文件路径
        """
        # 确保文件名安全
        safe_name = re.sub(r'[^\w\-\.]', '_', original_filename)
        if not safe_name.endswith('.vcf.gz') and not safe_name.endswith('.vcf'):
            safe_name = f"{safe_name}.vcf.gz"
        
        filename = f"{task_id}_{safe_name}"
        filepath = os.path.join(self.uploads_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"上传文件已保存: {filepath}")
        return filepath
    
    def list_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        列出最近的填充任务
        
        Args:
            limit: 返回的最大任务数
            
        Returns:
            任务列表
        """
        tasks = []
        
        # 扫描输出目录中的结果文件
        if os.path.isdir(self.output_dir):
            for filename in sorted(os.listdir(self.output_dir), reverse=True):
                if not filename.endswith('.vcf.gz') or '_imputed_' not in filename:
                    continue
                
                filepath = os.path.join(self.output_dir, filename)
                stat = os.stat(filepath)
                
                # 提取任务信息
                # 文件名格式: {original}_imputed_{timestamp}.vcf.gz
                base_name = filename.replace('.vcf.gz', '')
                
                tasks.append({
                    'output_file': filename,
                    'output_path': filepath,
                    'size_mb': round(stat.st_size / (1024 * 1024), 2),
                    'created_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    'task_type': 'imputation',
                    'status': 'completed'
                })
                
                if len(tasks) >= limit:
                    break
        
        return tasks
    
    def cleanup_old_files(self, max_age_hours: int = 24) -> Dict[str, Any]:
        """
        清理旧的临时文件
        
        Args:
            max_age_hours: 文件最大保留时间（小时）
            
        Returns:
            清理结果
        """
        import time
        
        cutoff_time = time.time() - (max_age_hours * 3600)
        cleaned = {'uploads': 0, 'outputs': 0, 'errors': []}
        
        for directory, key in [(self.uploads_dir, 'uploads'), (self.output_dir, 'outputs')]:
            if not os.path.isdir(directory):
                continue
            
            for filename in os.listdir(directory):
                filepath = os.path.join(directory, filename)
                if not os.path.isfile(filepath):
                    continue
                
                try:
                    if os.path.getmtime(filepath) < cutoff_time:
                        os.remove(filepath)
                        cleaned[key] += 1
                except Exception as e:
                    cleaned['errors'].append(f"删除 {filepath} 失败: {e}")
        
        return cleaned


# 单例实例
_imputation_tool_instance: Optional[ImputationTool] = None


def get_imputation_tool() -> ImputationTool:
    """获取 ImputationTool 单例实例"""
    global _imputation_tool_instance
    if _imputation_tool_instance is None:
        _imputation_tool_instance = ImputationTool()
    return _imputation_tool_instance
