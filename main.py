import os
import re
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yt_dlp
from contextlib import asynccontextmanager
import uvicorn

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 存储下载任务的状态
download_tasks: Dict[str, Dict[str, Any]] = {}

def sanitize_filename(filename: str) -> str:
    """清理文件名，移除不合法字符"""
    # 替换不合法字符
    illegal_chars = '<>:"/\\|?*'
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    # 限制长度
    return filename[:100]

def format_size(bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024
    return f"{bytes:.2f} TB"

def find_ffmpeg():
    """查找 FFmpeg ���装路径"""
    import shutil
    import os
    
    # 首先使用 shutil.which 查找
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
        
    # 检查常见安装路径
    common_paths = [
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser("~") + r"\ffmpeg\bin\ffmpeg.exe",
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
            
    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时的初始化
    logger.info("Application starting up...")
    
    # 检查和创建必要的目录
    for dir_name in ["static", "templates", "downloads"]:
        dir_path = os.path.abspath(dir_name)
        if os.path.exists(dir_path):
            logger.info(f"Directory exists: {dir_path}")
        else:
            logger.error(f"Directory missing: {dir_path}")
            if dir_name == "downloads":
                os.makedirs(dir_path)
                logger.info(f"Created downloads directory: {dir_path}")
    
    yield
    
    # 关闭时的清理工作
    logger.info("Application shutting down...")

app = FastAPI(lifespan=lifespan)

# 挂载静态文件和下载目录
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")
logger.info("Mounted static and downloads directories")

# 设置模板
templates = Jinja2Templates(directory="templates")

def get_video_info(url: str) -> Dict[str, Any]:
    """获取视频信息"""
    logger.info(f"开始获取视频信息: {url}")
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False  # 获取完整信息
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("正在提取视频信息...")
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise ValueError("无法获取视频信息")
            
            # 检查是否有可用的格式
            formats = info.get('formats', [])
            video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            
            logger.info(f"找到 {len(video_formats)} 个可用视频格式")
            if not video_formats:
                logger.info("没有找到同��包含视频和音频的格式，将使用最佳视频和音频组合")
                return info
            
            # 记录可用格式信息
            for fmt in video_formats:
                logger.info(
                    f"可用格式: {fmt['format_id']} - "
                    f"质量: {fmt.get('height', 'unknown')}p - "
                    f"编码: {fmt.get('vcodec', 'unknown')} - "
                    f"音频: {fmt.get('acodec', 'unknown')} - "
                    f"FPS: {fmt.get('fps', 'unknown')}"
                )
            
            # 选择最佳格式
            best_format = None
            for fmt in video_formats:
                if not best_format or fmt.get('height', 0) > best_format.get('height', 0):
                    best_format = fmt
            
            if best_format:
                logger.info(f"选择的最佳格式: {best_format['format_id']}")
                info['best_format'] = best_format
            
            return info
            
    except Exception as e:
        logger.error(f"获取视频信息时出错: {str(e)}", exc_info=True)
        return {'error': str(e)}

async def download_video(url: str, video_id: str):
    """异步下载视频"""
    logger.info(f"开始下载视频 ID: {video_id}, URL: {url}")
    download_tasks[video_id] = {
        'status': 'downloading',
        'progress': 0,
        'speed': '0 KB/s',
        'eta': 'unknown'
    }
    
    # 检查 FFmpeg 是否可用
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        error_msg = "未安装 FFmpeg。请安装 FFmpeg 后再试。Windows 用户可以使用: choco install ffmpeg"
        logger.error(error_msg)
        download_tasks[video_id].update({
            'status': 'error',
            'error': error_msg
        })
        return
    
    logger.info(f"找到 FFmpeg: {ffmpeg_path}")
    
    def progress_hook(d):
        """下载进度回调函数"""
        try:
            if d['status'] == 'downloading':
                # 计算下载进度
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded_bytes = d.get('downloaded_bytes', 0)
                
                if total_bytes > 0:
                    progress = (downloaded_bytes / total_bytes) * 100
                    speed = d.get('speed', 0)
                    eta = d.get('eta', 'unknown')
                    
                    # 更新任务状态
                    download_tasks[video_id].update({
                        'status': 'downloading',
                        'progress': round(progress, 2),
                        'speed': format_size(speed) + '/s' if speed else 'unknown',
                        'eta': str(eta) + 's' if isinstance(eta, (int, float)) else eta,
                        'total_bytes': total_bytes,
                        'downloaded_bytes': downloaded_bytes
                    })
                    
                    # 记录详细的进度信息
                    logger.debug(
                        f"下载进度: {progress:.2f}% - "
                        f"速度: {format_size(speed)}/s - "
                        f"剩余时间: {eta}s - "
                        f"已下载: {format_size(downloaded_bytes)} / {format_size(total_bytes)}"
                    )
                
            elif d['status'] == 'finished':
                # 更新状态为处理中
                download_tasks[video_id].update({
                    'status': 'processing',
                    'progress': 100,
                    'speed': '完成',
                    'eta': '处理中'
                })
                logger.info(f"下载完成，正在处理音视频: {video_id}")
                
            elif d['status'] == 'error':
                # 处理错误状态
                error_msg = d.get('error', 'Unknown error')
                download_tasks[video_id].update({
                    'status': 'error',
                    'error': error_msg
                })
                logger.error(f"下载出错: {error_msg}")
                
        except Exception as e:
            # 记录任何处理进度时的错误
            logger.error(f"处理下载进度时出错: {str(e)}", exc_info=True)
            download_tasks[video_id].update({
                'status': 'error',
                'error': f"进度处理错误: {str(e)}"
            })
    
    try:
        # 首先获取视频信息
        info = get_video_info(url)
        if 'error' in info:
            raise ValueError(info['error'])
            
        # 检查是否有可用的格式
        if not info.get('formats'):
            logger.error("没有找到可用的视频格式")
            raise ValueError("该视频没有可用的下载格式，可能是因为：\n1. 视频有版权限制\n2. 视频在您的地区不可用\n3. 视频已被删除或设为私有")
        
        # 生成安全的文件名
        title = info.get('title', 'video')
        safe_title = sanitize_filename(title)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_template = os.path.join(
            os.path.abspath("downloads"),
            f'{safe_title}_{timestamp}.%(ext)s'
        )
        logger.info(f"输出文件模板: {output_template}")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/bestvideo+bestaudio/best',
            'outtmpl': output_template,
            'progress_hooks': [progress_hook],
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'prefer_ffmpeg': True,
            'ffmpeg_location': ffmpeg_path,
            'quiet': False,
            'no_warnings': False,
            'format_sort': [
                'res:1080',
                'ext:mp4:m4a',
                'codec:h264:aac',
                'size',
                'br',
                'fps'
            ],
            'format_sort_force': True,
            'postprocessor_args': [
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-strict', 'experimental'
            ],
        }
        
        logger.info(f"使用格式下载: {ydl_opts['format']}")
        
        # 开始下载
        logger.info(f"开始下载视频: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # 取下载后的文件名
        filename = output_template % {'ext': 'mp4'}
        if not os.path.exists(filename):
            raise FileNotFoundError(f"下载超时或文件未找到: {filename}")
        
        # 更新任务状态为完成
        download_tasks[video_id].update({
            'status': 'completed',
            'filename': os.path.basename(filename),
            'path': f"/downloads/{os.path.basename(filename)}",
            'info': {
                'title': info.get('title', '未知标题'),
                'duration': str(datetime.fromtimestamp(info.get('duration', 0)).strftime('%H:%M:%S')) if info.get('duration') else '未知时长',
                'author': info.get('uploader', '未知作者'),
                'description': info.get('description', '无描述'),
                'filesize': format_size(os.path.getsize(filename)),
            }
        })
        logger.info(f"下载任务 {video_id} 完成: 成功")
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"下载视频时出错: {error_msg}", exc_info=True)
        download_tasks[video_id].update({
            'status': 'error',
            'error': error_msg
        })

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """主��"""
    # 获取下载的视频列表
    downloads_dir = os.path.abspath("downloads")
    videos = []
    
    if os.path.exists(downloads_dir):
        for filename in os.listdir(downloads_dir):
            if filename.endswith('.mp4'):
                file_path = os.path.join(downloads_dir, filename)
                videos.append({
                    'path': f"/downloads/{filename}",
                    'info': {
                        'title': filename,
                        'filesize': format_size(os.path.getsize(file_path)),
                        'description': ''  # 添加空的描述
                    }
                })
    
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "videos": videos}
    )

@app.post("/download")
async def start_download(url: str = Form(...)):
    """开始下载视频"""
    try:
        logger.info(f"收到下载请求: {url}")
        
        # 验证 URL
        if not url.startswith(('http://', 'https://')):
            raise ValueError("请输入有效的 URL")
        
        # 获取视频信息
        logger.info("正在获取视频信息...")
        info = get_video_info(url)
        if 'error' in info:
            raise ValueError(info['error'])
        
        # 创建下载任务
        video_id = str(len(download_tasks))
        logger.info(f"创建下载任务 ID: {video_id}")
        
        # 启动异步下载
        asyncio.create_task(download_video(url, video_id))
        
        return JSONResponse({
            'status': 'success',
            'message': '开始下载',
            'video_id': video_id
        })
        
    except Exception as e:
        logger.error(f"处理下载请求时出错: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={'error': str(e)}
        )

@app.get("/status/{video_id}")
async def get_status(video_id: str):
    """获取下载状态"""
    if video_id not in download_tasks:
        return JSONResponse(
            status_code=404,
            content={'error': '任务不存在'}
        )
    return download_tasks[video_id]

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有请求"""
    logger.info(f"Request: {request.method} {request.url}")
    try:
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": "Internal server error"}
        )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """处理 404 错误"""
    logger.warning(f"Not found: {request.url}")
    return JSONResponse(
        status_code=404,
        content={"message": "Resource not found"}
    )

@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """处理 500 错误"""
    logger.error(f"Server error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True) 