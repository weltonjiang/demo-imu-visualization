# 📡 IMU Visualization Demo

English | [中文](README_zh.md)

This project is built on the [Quectel Pi M2 smart mainboard](https://www.quectel.com.cn/product/quectel-pi-m2). An MPU6050 is connected to the 40-pin header I2C bus (I2C7, `/dev/i2c-7` on this board); the board samples it at 100 Hz by default and runs a six-axis attitude fusion, while the browser renders a 3D board, an artificial horizon and angle charts in real time. Tilt or rotate the board in your hand and the touchscreen and a PC browser on the same LAN both follow the motion. The UI also provides gyro bias calibration, yaw reset, pause and fullscreen; every reading comes from the real MPU6050.

![IMU Visualization running on a monitor, with the physical M2 board and MPU6050 held in the foreground](assets/demo_imu_visualization.png)

▶ **[Watch the demo video](assets/demo_imu_visualization.mp4)** (about 48 s)

## 🎯 Features

- **Live 3D attitude**: the default view is top-down; the M2 board follows the fused quaternion; drag with touch or mouse to orbit and double-click to restore the top view
- **Motion direction arrow**: a deliberate push (horizontal acceleration above 0.7 m/s² for at least 80 ms) captures the heading and shows a full-length amber arrow in the upper-left MOTION indicator for about 0.7 s. The hand's braking stroke is ignored so the arrow does not flip after the board stops, and small nudges or taps are filtered out. This is a relative-motion cue, not absolute positioning
- **Real board texture**: the M2 top and bottom faces use photos of the actual board, so the 40-pin header, Ethernet, USB, SD card and silkscreen stay recognisable while it rotates
- **Artificial horizon**: a dedicated fullscreen attitude indicator with pitch ladder, roll scale and yaw tape for quick reading on a touchscreen
- **Three-axis readouts and charts**: roll, pitch, yaw, three-axis acceleration, angular rate and temperature, with a 20-second history chart
- **Bias calibration**: keep the board still for about 2 seconds to measure the three gyro biases; if the board moves, the previous bias is kept and the reason is shown
- **Yaw reset**: make the current heading the new zero without changing roll and pitch; yaw is gyro-integrated, shown as a compass heading `000–360°` (clockwise positive), and the UI states that there is no magnetometer
- **Two displays**: open the UI on the board touchscreen in Chromium kiosk mode, or from a PC over the LAN; layouts for 1024×600 and 1440×900 are covered
- **No runtime dependencies, automatic recovery**: the web server, I2C transport and fusion use only the Python standard library; the sensor reconnects automatically after a dropout and the state is visible on the page

## 📋 Requirements

### Hardware

- Quectel Pi M2 smart mainboard (Debian 13 factory image, 40-pin header)
- MPU6050 sensor module (GY-521 and similar, 3.3 V supply)
- Four jumper wires: VCC, GND, SDA, SCL
- Touchscreen or HDMI monitor; optional USB keyboard and mouse
- Optional LAN connection for viewing from a PC browser

| MPU6050 pin | M2 40-pin | Notes |
| --- | --- | --- |
| VCC | 3V3 (pin 1) | Must be 3.3 V, never 5 V |
| GND | GND (pin 6) | Common ground |
| SDA | GPIO2 / SDA (pin 3) | I2C7 data |
| SCL | GPIO3 / SCL (pin 5) | I2C7 clock |
| AD0 | leave open | Address `0x68`; `0x69` when tied to 3V3 |
| INT | not connected | Polling is used instead of interrupts |

The 40-pin header I2C bus enumerates as `/dev/i2c-7` on this board. At startup the program scans every `/dev/i2c-*` bus and both `0x68/0x69`, so another bus or `0x69` needs no configuration change; here the MPU6050 is found on `/dev/i2c-7` at `0x69` (AD0 high) and selected automatically.

### Software

- OS: Debian 13 (the Quectel Pi M2 factory image; no reflash needed)
- Python 3.9 or newer; `venv` is optional and there are no third-party runtime dependencies
- Device node: `/dev/i2c-7` on this board (any `/dev/i2c-N` is auto-detected)
- Network port: `8081/tcp` (change with `--port`)
- Browser: Chromium or Google Chrome; the 3D view needs WebGL, while the horizon view does not
- The current user must belong to the `i2c` group; the installer checks this and prints a hint

## 🚀 Installation and running

1. On the board, install git and clone the repository into `~/projects/`:

```bash
sudo apt update
sudo apt install -y git
cd ~/projects
git clone https://github.com/Quectel-Pi/demo-imu-visualization.git
```

2. Enter the project and run the deployment helper. It is idempotent: it creates or reuses `.venv`, checks dependencies, fixes executable bits and probes the I2C device:

```bash
cd ~/projects/demo-imu-visualization
./install.sh
```

3. Run a read-only self-check to verify the Python modules, I2C bus, MPU6050 address and access URL:

```bash
./scripts/preflight.sh
```

A line such as `found MPU6050 on /dev/i2c-7 at 0x69 (WHO_AM_I 0x68)` means the wiring and permissions are correct.

4. Start the program. It prints every reachable URL; open one of them in a PC browser:

```bash
./run.sh
```

Typical output:

```text
Open from :
  http://192.168.1.50:8081/  (eth0)
```

The board IP changes with the network; use the printed value. If you forget it, run `~/imu-url` on the board (created by `install.sh`) or inspect the network interfaces again. To change the port:

```bash
./run.sh --port 8090
```

The default port is `8081`. To pin a different port, append `--port <port>` to `ExecStart` in the unit file.

### Optional: start on boot

Copy the shipped systemd unit and enable it:

```bash
sudo cp scripts/demo-imu-visualization.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now demo-imu-visualization
```

The unit assumes the project lives in `~/projects/demo-imu-visualization`; adjust `User` and `WorkingDirectory` if your board account or path differs. To launch the touchscreen page in fullscreen Chromium:

```bash
./scripts/start_kiosk.sh
```

## 🎛️ Usage

The left side is the 3D board or artificial horizon stage, the right side holds Euler angles, sensor values, controls and hardware information, and the bottom shows the 20-second attitude chart. All UI text and status messages are English so the same page works on the touchscreen and on a PC.

- **Observe the attitude**: the default view is top-down. Tilt or rotate the board slowly; the 3D board follows the fused orientation. Move the board and the amber arrow in the upper-left MOTION indicator points in the movement direction; the board itself stays centred. Drag to orbit and double-click to restore the top view
- **Switch views**: use `3D board` and `Horizon` in the stage header. The horizon view includes a pitch ladder, roll scale and yaw tape
- **Calibrate the gyro**: place the board flat and still, then click `Calibrate`. It takes about 2 seconds and shows Calibrating; if motion is detected, the measurement is not applied
- **Reset yaw**: click `Reset yaw` to make the current heading zero. Roll and pitch keep their gravity reference. Yaw is a compass heading (`000–360°`, clockwise positive) and drifts slowly without a magnetometer, so reset it whenever needed
- **Pause and fullscreen**: `Pause` freezes the stream to inspect a pose; the top-right button or `F` toggles fullscreen
- **View from a PC**: open the printed `http://<board-ip>:8081/` on the same LAN; the page is identical to the touchscreen
- **First start**: the program performs a still calibration and records the current pose as the level reference. If the board is moving at that moment the page reports an uncertain calibration; keep it still and click `Calibrate` manually
- **Mounting**: startup calibration also records the sensor mounting rotation and normalizes the 1 g magnitude, so an inverted or tilted module still starts as a level, upright board
- **About the 3D model**: the M2 board uses top and bottom photo textures of the real board. The MPU6050 is an external sensor and is not drawn as an extra module or jumper wires in the 3D view; the orientation and relative translation come from it. The translation is shown as a relative-motion arrow, not absolute positioning or a mechanical drawing

### Protocol summary

- **Bus and address**: I2C; the 40-pin header bus is `/dev/i2c-7` on this board; 7-bit address `0x68`, or `0x69` when `AD0` is tied high
- **Read pattern**: one 14-byte burst from `0x3B` (three-axis acceleration, temperature, three-axis gyro) through the i2c-dev ioctl, with no smbus dependency
- **Ranges and bandwidth**: gyro ±500 °/s, accelerometer ±2 g, DLPF 44 Hz, 100 Hz sampling
- **Fusion**: six-axis Madgwick complementary filter; the accelerometer corrects roll/pitch, the gyro integrates yaw, and there is no magnetometer
- **Yaw display**: compass heading `000–360°`, clockwise positive; the Euler panel, stage readout, horizon tape and 20-second chart use the same range
- **Mounting reference**: still calibration records the mounting rotation and 1 g scale, and makes the current pose the 0° reference; set `sensor.level_on_start` to `false` for gravity-absolute axes
- **Browser link**: the static page and JSON API are served by a Python standard-library HTTP server; the page requests `/api/attitude` about every 33 ms and interpolates the quaternion locally
- **Main endpoints**: `/api/attitude`, `/api/status`, `/api/calibrate`, `/api/tare`, `/api/pause`

### Axis order and mounting

By default the GY-521 is assumed face-up, with `+X` to the right of the board, `+Y` toward the top and `+Z` out of the board surface. If the module is rotated or flipped, edit `sensor.axis_map` in `config.json`. Each target axis selects a source axis and may be negated:

```jsonc
{
  "sensor": {
    "axis_map": {
      "x": "-y",
      "y": "x",
      "z": "z"
    }
  }
}
```

The example above represents a module rotated 90° clockwise on the board. Restart the program after the change and run the still calibration again. `sensor.level_on_start` defaults to `true`: startup calibration makes the current still pose the 0° level reference and records the mounting rotation plus the 1 g scale. Set it to `false` to show gravity-absolute orientation instead. The I2C address, ranges, sample rate and fusion gain are also in `config.json`; no source change is needed.

## 📁 Project structure

```text
demo-imu-visualization/
├── src/
│   ├── main.py                    # entry point: args, HTTP server, shutdown
│   └── attitude/
│       ├── config.py              # load config.json and merge CLI overrides
│       ├── imu.py                 # MPU6050 i2c-dev driver, ranges, bus probe
│       ├── fusion.py              # quaternion, Madgwick, bias and yaw tare
│       ├── service.py             # sampling thread, calibration, pause
│       ├── server.py              # stdlib HTTP server and JSON API
│       └── netinfo.py             # LAN address discovery
├── web/
│   ├── index.html                 # single-page UI
│   ├── style.css                  # dark instrument styling and responsive layout
│   ├── app.js                     # polling, smoothing, buttons and state
│   ├── scene3d.js                 # Three.js board scene and orbit camera
│   ├── horizon.js                 # artificial horizon and yaw tape
│   ├── chart.js                   # 20-second three-row attitude chart
│   ├── assets/m2-board-top.png    # M2 board top photo texture (UI)
│   ├── assets/m2-board-bottom.png # M2 board bottom photo texture (UI)
│   └── vendor/three.min.js        # three.js r140 (MIT)
├── scripts/
│   ├── preflight.sh               # read-only self-check
│   ├── show_access_url.sh         # print LAN access URLs
│   ├── start_kiosk.sh             # Chromium touchscreen fullscreen launcher
│   └── demo-imu-visualization.service
├── assets/                        # README image and demo video
├── config.json                    # bus, address, ranges, sample rate, axis map
├── install.sh                     # idempotent venv, deps, permissions, probe
├── run.sh                         # launcher, supports --port
├── requirements.txt               # no third-party runtime dependencies
├── README.md                      # English documentation (this file)
├── README_zh.md                   # Chinese documentation
└── THIRD_PARTY_LICENSES.md        # three.js license
```

## 📚 More documentation

- Third-party components and licenses: see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)
- Read-only checks on the board:

```bash
PYTHONPATH=src python3 -m attitude.imu --probe
PYTHONPATH=src python3 -m attitude.imu --watch
```

- The board reads the MPU6050 at `/dev/i2c-7`, address `0x69`; the UI shows LIVE at 100 Hz. If the sensor is disconnected or rewired, the page shows Sensor lost and keeps reconnecting; it never produces simulated readings
- The full test suite lives in the development workspace `test_tools/` (fusion units, hardware-failure service tests and HTTP tests) and is not shipped inside the project directory

## 📮 Reporting issues

If you run into a problem, post a technical question in the [Quectel Pi developer forum](https://forumschinese.quectel.com/c/quectel-pi/58); our support team will help. Issues and pull requests that improve this project are welcome.
