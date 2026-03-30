# ─── 数据输出根目录
DATA_ROOT = "data"

# 受试者编号（"P1" "P2" "P3"）
PARTICIPANT_ID = "P1"

# ─── 摄像头设置 
FACIAL_CAMERA_INDEX  = 0      # 面部摄像头的系统设备索引（camera 1）
TRAFFIC_CAMERA_INDEX = 1      # 交通摄像头的系统设备索引（camera 2）

#720p = 1280x720 | 1080p = 1920x1080 | 4K = 3840x2160
FRAME_WIDTH  = 1280           # 录制分辨率宽度（像素）
FRAME_HEIGHT = 720            # 录制分辨率高度（像素）
FPS          = 30             # 录制帧率（fps）

# ─── 视频分段设置 
VIDEO_SAVE_INTERVAL_MINUTES = 1   # 每隔 N 分钟保存一段视频文件（分钟）

# ─── GPS 串口设置
GPS_PORT     = "COM7"         # GPS 接收机串口号
GPS_BAUDRATE = 4800           # BU-353N5 默认波特率
GPS_TIMEOUT  = 1              # 串口读取超时（秒）

# ─── 数据采集频率 
GPS_QUERY_INTERVAL = 10       # 秒

# ─── Azure Maps API 密钥 
import os
AZURE_MAPS_KEY = os.environ.get("AZURE_MAPS_KEY")

# ─── 交通事件查询半径（km）
INCIDENT_RADIUS_KM = 1.0

# ─── Azure Maps API 端点 
WEATHER_API_URL           = "https://atlas.microsoft.com/weather/currentConditions/json"
TRAFFIC_FLOW_SEGMENT_URL  = "https://atlas.microsoft.com/traffic/flow/segment/json"
TRAFFIC_INCIDENT_VIEWPORT = "https://atlas.microsoft.com/traffic/incident/viewport/json"
TRAFFIC_INCIDENT_DETAIL   = "https://atlas.microsoft.com/traffic/incident/detail/json"

# ─── API 请求超时（秒）
REQUEST_TIMEOUT = 15


