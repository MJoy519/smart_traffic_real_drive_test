# 智慧交通导航系统

数码港 ↔ 马鞍山，支持 Fast 最快路线 与 Emotion 情感路线 双模式导航。

## 项目结构

```
google_interface/
├── backend/                  # Python FastAPI 后端
│   ├── main.py               # API 入口（端口 8001）
│   ├── config.py             # 路线经纬度、分段点、测试模式开关
│   ├── .env                  # API 密钥（填入后生效）
│   ├── requirements.txt
│   ├── modules/
│   │   ├── traffic_calculator.py  ← 核心：输出 1 或 2
│   │   ├── segment_analyzer.py    ← 调用 Google Distance Matrix API
│   │   └── route_selector.py      ← 对外接口封装
│   └── routes/
│       ├── emotion_route_1.json   # 北线（西区隧道）固定数据
│       └── emotion_route_2.json   # 南线（香港仔/1号公路）固定数据
│
└── frontend/                 # React + Vite 前端
    ├── src/
    │   ├── App.jsx            # 主状态机（工作流管理）
    │   ├── components/
    │   │   ├── MapView.jsx         # Google Maps 渲染（3条路线）
    │   │   ├── ControlPanel.jsx    # 左侧控制面板
    │   │   ├── RouteCard.jsx       # 单条路线卡片
    │   │   └── NavigationBar.jsx   # 导航模式底部栏
    │   ├── hooks/
    │   │   └── useGeolocation.js   # 定位 + 到达起点判定
    │   └── api/
    │       └── routeApi.js         # 后端 API 调用
    └── .env                   # 填入 Google Maps API Key
```

## 快速启动

### 1. 配置 API Key

**后端** `backend/.env`：
```
GOOGLE_MAPS_API_KEY=你的密钥
```

**前端** `frontend/.env`：
```
VITE_GOOGLE_MAPS_API_KEY=你的密钥
```

> API Key 需开启：Maps JavaScript API + Distance Matrix API

### 2. 启动后端

```powershell
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --port 8001 --reload
```

### 3. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

## 功能流程

```
选择起点（数码港 / 马鞍山）
    ↓
地图展示 3 条路线（蓝=最快，绿=情感1，橙=情感2）
    ↓
选择模式
 ├─ Fast：高亮蓝色路线 → 选择出发时间 → 开始导航
 └─ Emotion：
       → 检查当前位置是否到达起点（半径500m内）
       → 点击"计算最优情感路线"
       → 后端调用 Google Distance Matrix API 分析各段拥堵
       → 高亮推荐路线（拥堵指数更低的一条）
       → 选择出发时间 → 开始导航
```

## 测试模式

`backend/config.py` 中：
```python
TEST_MODE = True             # 跳过 API，直接返回指定路线
TEST_MODE_FORCED_ROUTE = 1   # 1=北线 / 2=南线
```

## 情感路线说明

| 路线 | 走向 | 关键道路 | 距离 |
|------|------|----------|------|
| 路线1（北线） | 数码港→堅彌地城→西区隧道→九龙→大老山隧道→马鞍山 | 域多利道、4号公路、3号公路、7号公路 | 29.6 km |
| 路线2（南线） | 数码港→薄扶林→香港仔→1号公路→东区走廊→大老山隧道→马鞍山 | 薄扶林道、石排灣道、1号公路 | 31.2 km |

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /` | GET | 健康检查 |
| `POST /calculate-emotion-route` | POST | 计算最优情感路线（返回1或2） |
| `GET /route-data/{1\|2}` | GET | 获取情感路线固定数据 |
| `GET /origins` | GET | 获取起终点信息 |
| `GET /config/test-mode` | GET | 获取测试模式配置 |
