# Feature Comparison: OpenGNARBOX vs. Original GNARBOX 2.0

This document outlines the current capabilities of the OpenGNARBOX software stack compared to the original proprietary firmware found on GNARBOX 2.0 devices.

## 📊 Comparison Table

| Feature | Original GNARBOX 2.0 | OpenGNARBOX (Current) | Status |
| :--- | :---: | :---: | :--- |
| **On-Device Backups** | ✅ (Single Button) | ✅ | In Development |
| **Built-in OLED Screen** | ✅ (Full Menu) | ✅ | via Original interfaces |
| **Directional Buttons** | ✅ (Navigation) | ✅ | via Original interfaces |
| **User Interface** | ⚠️ (Legacy Mobile App) | ✅ (Universal Web App) | **Improved (No App Needed)** |
| **Performance** | ⚠️ (Legacy Bloat) | ✅ (Lightweight Core) | **Improved (Faster Indexing)** |
| **Deduplication** | ✅ | ✅ (Deep Hash) | **Improved** |
| **Transfer Progress** | ✅ (On-Device Screen + App) | ✅ (On-screen +  Web App) | Feature Parity |
| **Security** | ❓ (Proprietary unsecured Firmware) | ✅ (Sandboxed, Secure Coding Practices) | **Improved** |
| **Multi-File Downloads** | ⚠️ (Limited) | ✅ (Session-Based) | **Improved** |
| **Battery Monitoring** | ✅ | ✅ (Via Web App) | Feature Parity |
| **SD/NVMe Scanning** | ✅ | ✅ (Via Web App) | Feature Parity |

---

## 🛠️ Original GNARBOX 2.0 Capabilities

The original device is famous for its **"One-Touch" backup** capability and its rugged, screen-integrated workflow.

### 📱 On-Device Screen & Navigation
The original firmware includes a complete OS accessible via the built-in OLED screen and four-way directional buttons.
- **Status Dashboard**: Real-time battery, storage, and thermal metrics.
- **Backup Menu**: Start "preset" backups (e.g., SD to NVMe) without any external device.
- **Feedback**: Immediate success/fail indicators and progress bars on the OLED.

### ⚡ Physical Logic
The device logic is tied heavily to the physical buttons. Pressing the "Down" button usually triggers a pre-configured backup folder creation and ingestion process.

---

## 🚀 OpenGNARBOX Capabilities (Current Phase)

Our current implementation focuses on the **Core Engine** and a **Modern Web Interface** for professional media management.

### 🌐 Advanced Web UI (ImporTool)
While the original device relied heavily on native mobile apps that were often buggy, old and thus unsupported or OS-restricted, OpenGNARBOX provides a powerful, local-only web interface accessible from any browser on the same network as the device (Phone, Tablet, or Laptop).
- **Universal Access**: No "dumb" proprietary app to install. Just connect to the device's WiFi and open your browser.
- **Improved Speed**: The optimized Python core ensures that directory scanning and indexing are noticeably faster than the original firmware.
- **Full File Browser**: Manage and download files directly from the device via a professional explorer-like interface.
- **WebSocket Progress**: Detailed per file progress bars for file copy/move operations delivered in real-time.
- **Smart Organization**: Automatically re-structures your media library based on metadata and camera models during ingestion.

### 🛡️ Hardened Security
OpenGNARBOX introduced a sandboxed file system environment. Even with administrator access to the WebUI, the backend strictly prevents any operations outside of the authorized `/media` and `/tmp` paths.

### 🏗️ Future Milestones (Reverse Engineering)
We are currently working on the kernel drivers and userspace utilities required to:
1.  **Re-enable the OLED Display**: Driving the screen via custom I2C/SPI drivers. ✅complete ✅
2.  **Mapping Hardware Buttons**: Listening for GPIO events from the physical navigation buttons ✅complete ✅ to trigger the **"One-Touch Backup"** logic without the WebUI. working
