# YouTube 视频下载器

这是一个基于 FastAPI 和 yt-dlp 的 YouTube 视频下载器。

## 功能特点

- 支持下载 YouTube 视频
- 自动选择最佳视频质量
- 实时显示下载进度
- 支持视频格式转换
- 美观的 Web 界面

## 安装要求

- Python 3.8+
- FFmpeg
- 依赖包（见 requirements.txt）

## 安装步骤

1. 克隆仓库：
```bash
git clone [你的仓库URL]
cd youtube_download
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 安装 FFmpeg：
- Windows 用户：`choco install ffmpeg`
- Linux 用户：`sudo apt-get install ffmpeg`
- Mac 用户：`brew install ffmpeg`

## 使用方法

1. 启动服务器：
```bash
python main.py
```

2. 打开浏览器访问：`http://127.0.0.1:8001`

3. 输入 YouTube 视频链接并点击下载

## 注意事项

- 请确保已安装 FFmpeg
- 下载的视频将保存在 downloads 目录
- 请遵守 YouTube 的服务条款和版权规定

## 许可证

MIT License 