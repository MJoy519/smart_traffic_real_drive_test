from dotenv import load_dotenv
load_dotenv()

# ─── 数据输出根目录
DATA_ROOT = "data"

# 受试者编号（"P1" "P2" "P3"）
PARTICIPANT_ID = "P1"

# ─── 摄像头设置 
FACIAL_CAMERA_INDEX  = 2      # 面部摄像头的系统设备索引（camera 1）
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
GPS_TIMEOUT  = 1              # 串口单次 read 超时（秒），collect 内使用

# ─── 设备测试（test.py）
TEST_CAMERAS = False          # True：仅跑摄像头预览，跳过 GPS 测试段
GPS_TEST_ACQUIRE_TIMEOUT_SEC = 5   # 设备测试中等待卫星定位的总超时（秒）

# ─── 仅摄像头采集模式
# True（默认）：禁用 GPS / Azure API 采集，只录摄像头视频
# False：启用完整 GPS + Azure API 采集
CAMERA_ONLY_MODE = True

# ─── 采集定位（collect.py）
# True：GPS/Azure 使用下方固定经纬度；False：使用串口 GPS 实时定位
TEST_MODE = True
TEST_LOCATION_LON = 113.9640039313171   # 固定点经度
TEST_LOCATION_LAT = 22.586732532117953  # 固定点纬度

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


