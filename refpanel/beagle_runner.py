#!/usr/bin/env python3
"""
Beagle填充运行器 - 管理基因型填充任务的执行
支持Beagle 5.x版本，提供参数配置、进度监控和错误处理
"""

import os
import re
import subprocess
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    """推断仓库根目录（beagle_runner.py 位于 repo/refpanel/）"""
    return Path(__file__).resolve().parent.parent


class ImputationStatus(Enum):
    """填充任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ImputationConfig:
    """填充配置"""
    # Beagle参数
    window_size: float = 100.0  # cM
    overlap: float = 10.0  # cM
    ne: int = 1000000  # 有效群体大小
    impute: bool = True
    gp: bool = True  # 输出基因型概率
    
    # 性能参数
    nthreads: int = 4
    
    # 路径配置
    java_path: str = "java"
    beagle_jar: Optional[str] = None
    
    def to_beagle_args(self) -> List[str]:
        """转换为Beagle命令行参数"""
        args = [
            f"window={self.window_size}",
            f"overlap={self.overlap}",
            f"ne={self.ne}",
            f"nthreads={self.nthreads}"
        ]
        
        if self.impute:
            args.append("impute=true")
        if self.gp:
            args.append("gp=true")
        
        return args


@dataclass
class ImputationTask:
    """填充任务"""
    task_id: str
    input_file: str
    reference_panel: str
    output_file: str
    config: ImputationConfig
    status: ImputationStatus = ImputationStatus.PENDING
    progress: float = 0.0
    message: str = ""
    log_output: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "input_file": self.input_file,
            "reference_panel": self.reference_panel,
            "output_file": self.output_file,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "error_message": self.error_message
        }


class BeagleRunner:
    """
    Beagle填充运行器
    
    功能：
    1. 管理Beagle填充任务的执行
    2. 监控任务进度
    3. 处理错误和异常
    4. 支持任务取消
    """
    
    # Beagle版本检测模式
    VERSION_PATTERN = re.compile(r'Beagle\s+(\d+\.\d+)')
    PROGRESS_PATTERN = re.compile(r'(\d+)%')
    
    def __init__(
        self,
        beagle_jar: Optional[str] = None,
        java_path: str = "java",
        work_dir: Optional[str] = None
    ):
        self.beagle_jar = beagle_jar or self._find_beagle_jar()
        self.java_path = java_path
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "beagle_work"
        
        # 任务管理
        self.tasks: Dict[str, ImputationTask] = {}
        self._running_processes: Dict[str, subprocess.Popen] = {}
        
        # 创建工作目录
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        # 检查Beagle
        self._check_beagle()
    
    def _find_beagle_jar(self) -> Optional[str]:
        """自动查找Beagle JAR文件"""
        # 常见路径
        search_paths = [
            str(_project_root() / "refpanel" / "beagle.jar"),
            "/usr/local/bin/beagle.jar",
            "/opt/beagle/beagle.jar",
            "./beagle.jar",
            "../beagle.jar",
        ]
        
        # 环境变量
        if 'BEAGLE_JAR' in os.environ:
            search_paths.insert(0, os.environ['BEAGLE_JAR'])
        
        for path in search_paths:
            if os.path.exists(path):
                return path
        
        # 搜索目录
        for pattern in ['**/beagle*.jar', '**/Beagle*.jar']:
            matches = list(Path('.').glob(pattern))
            if matches:
                return str(matches[0])
        
        return None
    
    def _check_beagle(self):
        """检查Beagle是否可用"""
        if not self.beagle_jar:
            logger.warning("未找到Beagle JAR文件，填充功能将不可用")
            return
        
        if not os.path.exists(self.beagle_jar):
            logger.warning(f"Beagle JAR文件不存在: {self.beagle_jar}")
            return
        
        try:
            # 测试运行获取版本
            cmd = [self.java_path, "-jar", self.beagle_jar, "version"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # 解析版本
            output = result.stdout + result.stderr
            match = self.VERSION_PATTERN.search(output)
            if match:
                version = match.group(1)
                logger.info(f"✓ Beagle版本: {version}")
            else:
                logger.info("✓ Beagle已安装")
                
        except Exception as e:
            logger.warning(f"Beagle检查失败: {e}")
    
    def is_available(self) -> bool:
        """检查Beagle是否可用"""
        return self.beagle_jar is not None and os.path.exists(self.beagle_jar)
    
    def create_task(
        self,
        input_file: str,
        reference_panel: str,
        output_prefix: Optional[str] = None,
        config: Optional[ImputationConfig] = None
    ) -> ImputationTask:
        """
        创建填充任务
        
        Args:
            input_file: 输入VCF文件
            reference_panel: 参考面板路径
            output_prefix: 输出前缀
            config: 填充配置
            
        Returns:
            填充任务
        """
        task_id = f"imp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if not output_prefix:
            output_prefix = str(self.work_dir / f"{task_id}_output")
        
        output_file = f"{output_prefix}.vcf.gz"
        
        task = ImputationTask(
            task_id=task_id,
            input_file=input_file,
            reference_panel=reference_panel,
            output_file=output_file,
            config=config or ImputationConfig()
        )
        
        self.tasks[task_id] = task
        
        logger.info(f"创建填充任务: {task_id}")
        
        return task
    
    def run_task(
        self,
        task_id: str,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> ImputationTask:
        """
        执行填充任务
        
        Args:
            task_id: 任务ID
            progress_callback: 进度回调函数
            
        Returns:
            任务结果
        """
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        
        if not self.is_available():
            task.status = ImputationStatus.FAILED
            task.error_message = "Beagle不可用"
            return task
        
        task.status = ImputationStatus.RUNNING
        task.start_time = datetime.now()
        task.message = "开始填充..."
        
        try:
            # 构建命令
            cmd = self._build_command(task)
            
            logger.info(f"执行命令: {' '.join(cmd)}")
            
            # 启动进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self._running_processes[task_id] = process
            
            # 读取输出
            for line in process.stdout:
                line = line.strip()
                task.log_output.append(line)
                
                # 解析进度
                progress = self._parse_progress(line)
                if progress is not None:
                    task.progress = progress
                    if progress_callback:
                        progress_callback(progress, line)
                
                # 更新消息
                if line:
                    task.message = line[:200]  # 限制长度
                
                logger.debug(f"[{task_id}] {line}")
            
            # 等待完成
            return_code = process.wait()
            
            if return_code == 0:
                task.status = ImputationStatus.COMPLETED
                task.progress = 100.0
                task.message = "填充完成"
                
                # 验证输出文件
                if not os.path.exists(task.output_file):
                    task.status = ImputationStatus.FAILED
                    task.error_message = "输出文件未生成"
            else:
                task.status = ImputationStatus.FAILED
                task.error_message = f"进程返回错误码: {return_code}"
            
        except Exception as e:
            task.status = ImputationStatus.FAILED
            task.error_message = str(e)
            logger.error(f"任务执行失败: {e}")
        
        finally:
            task.end_time = datetime.now()
            if task_id in self._running_processes:
                del self._running_processes[task_id]
        
        return task
    
    def _build_command(self, task: ImputationTask) -> List[str]:
        """构建Beagle命令"""
        cmd = [
            self.java_path,
            "-jar", self.beagle_jar,
            f"gt={task.input_file}",
            f"ref={task.reference_panel}",
            f"out={task.output_file.replace('.vcf.gz', '')}"
        ]
        
        # 添加配置参数
        cmd.extend(task.config.to_beagle_args())
        
        return cmd
    
    def _parse_progress(self, line: str) -> Optional[float]:
        """解析进度信息"""
        match = self.PROGRESS_PATTERN.search(line)
        if match:
            return float(match.group(1))
        return None
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否成功取消
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        if task.status != ImputationStatus.RUNNING:
            return False
        
        process = self._running_processes.get(task_id)
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
        
        task.status = ImputationStatus.CANCELLED
        task.end_time = datetime.now()
        task.message = "任务已取消"
        
        if task_id in self._running_processes:
            del self._running_processes[task_id]
        
        logger.info(f"任务已取消: {task_id}")
        return True
    
    def get_task(self, task_id: str) -> Optional[ImputationTask]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task = self.tasks.get(task_id)
        if task:
            return task.to_dict()
        return None
    
    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有任务"""
        return [task.to_dict() for task in self.tasks.values()]
    
    def cleanup_task(self, task_id: str):
        """清理任务临时文件"""
        task = self.tasks.get(task_id)
        if not task:
            return
        
        # 清理临时文件
        try:
            output_prefix = task.output_file.replace('.vcf.gz', '')
            for ext in ['.vcf.gz', '.log', '.bref3']:
                file_path = f"{output_prefix}{ext}"
                if os.path.exists(file_path):
                    os.remove(file_path)
        except Exception as e:
            logger.warning(f"清理任务文件失败: {e}")
    
    def get_default_config(self) -> ImputationConfig:
        """获取默认配置"""
        return ImputationConfig()
    
    def validate_input(
        self,
        input_file: str,
        reference_panel: str
    ) -> Dict[str, Any]:
        """
        验证输入文件
        
        Args:
            input_file: 输入文件
            reference_panel: 参考面板
            
        Returns:
            验证结果
        """
        issues = []
        
        # 检查输入文件
        if not os.path.exists(input_file):
            issues.append({"level": "error", "message": f"输入文件不存在: {input_file}"})
        elif not input_file.endswith(('.vcf', '.vcf.gz', '.bcf')):
            issues.append({"level": "warning", "message": "输入文件应为VCF或BCF格式"})
        
        # 检查参考面板
        if not os.path.exists(reference_panel):
            issues.append({"level": "error", "message": f"参考面板不存在: {reference_panel}"})
        
        # 检查Beagle
        if not self.is_available():
            issues.append({"level": "error", "message": "Beagle不可用，请检查安装"})
        
        return {
            "valid": len([i for i in issues if i['level'] == 'error']) == 0,
            "issues": issues
        }
