# OpenGNARBOX

> [!CAUTION]
> **EARLY DEVELOPMENT PHASE**
> This Repositorys content is currently in the **early stages of active development** and is primarily in a **testing and reverse engineering phase**. The complete OpenGNARBOX software stack is **not yet fully functional**. The custom firmware images will be released at a later date. Use with extreme caution.

> [UPDATE]
> **Reversing is done.** I have a locally working custom firwmare which runs on device. I am now in the so called "intergration hell" to get the new software stack and the hardware working together smoothly. i made good progress and should be able to release a beta version soon :) pls dont bug me about it tho 

For a detailed look at implemented features vs. original hardware capabilities, see [FEATURES.md](./FEATURES.md).

**The Open Firmware successor for GNARBOX 2.0 Hardware.**

OpenGNARBOX is a specialized software stack designed to replace the proprietary firmware on GNARBOX 2.0 (x86_64) devices. It transforms the device into a robust, secure, and fully source-available backup and organization tool for professional photographers and videographers.

## 📜 Motivation

Following the **bankruptcy of MyGnar Inc.**, the original GNARBOX hardware was left without official support, potentially turning thousands of high-end field backup devices into e-waste. Furthermore, analysis of the original proprietary firmware revealed significant security gaps and architectural vulnerabilities. 

OpenGNARBOX was born out of a necessity to provide a **secure, sustainable, and transparent** alternative that puts the hardware back in the hands of its owners, released as a source-available project.

## 🌟 Key Features

*   **Fail-Safe Ingestion**: Automated backup from SD to NVMe with SHA-256 verification.
*   **Professional Organization**: Smart pattern-based file organization with deep deduplication.
*   **Secure by Design**: Strict path validation and session-based downloads to prevent system escape.
*   **Modern Web UI**: Responsive, mobile-friendly interface for field use.
*   **Hardware Integration**: Real-time monitoring of SSD storage, battery levels, and mount status.

## 🏗️ Architecture

OpenGNARBOX is built with a decoupled, containerized architecture:

### [OpenGNAR Core (Backend)](./backend)
A lightweight, high-performance **FastAPI (Python)** server optimized for the device hardware.
- **Improved Performance**: Minimal overhead allows for significantly faster file operations and indexing than the original firmware.
- **App-Free Access**: No proprietary mobile app is required; the full experience is accessible via any modern web browser.
- Orchestrates file operations (copy, move, delete, hash).
- Monitors system status (battery, storage).
- Enforces security through a sandboxed path validation engine.
- Serves the compiled frontend assets.

### [ImporTool (Frontend)](./importool)
A professional-grade **React (TypeScript)** web application.
- Explorer-like file browser with multi-file management.
- Real-time progress monitoring via WebSockets.
- Intelligent organization rules and naming transformation.

---

## 🚀 Quick Start

The easiest way to run OpenGNARBOX is using Docker Compose.


### Running in Test/Mock Mode
To run without requiring hardware mounts:
```bash
docker-compose -f docker-compose.test.yml up
```

## 🛡️ Security & Reliability

OpenGNARBOX prioritizes the safety of your data:
- **Path Validation**: All API requests are checked against authorized media mount points (`/media/sd`, `/media/nvme`).
- **Session-Based Downloads**: Prevents URI length limitations and secures multi-file ZIP generation.
- **Atomic Operations**: Verification occurs before source deletion in "Move" mode.

---

## 🛠️ Development

### Backend Development
The backend is located in the `/backend` directory. It uses Python 3.11+.
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend Development
The frontend is located in the `/importool` directory.
```bash
cd importool
npm install
npm run dev
```

---
*OpenGNARBOX is an independent source-available project and is not affiliated with the original GNARBOX manufacturer.*

## 📄 License
This project is the intellectual property of **CyberTap IT & Security / Dominik W. Feger**. Use, modification, and redistribution are restricted under a custom proprietary license. 

See [LICENSE](./LICENSE) for full terms.

### 🤖 AI Assistance Disclosure
Parts of this project have been developed using AI-assisted coding tools. However, every line of code has been manually reviewed and verified by a human developer to ensure it adheres to best practices, security standards, and system integrity. This is not an AI slop project.

&copy; 2026 CyberTap IT & Security / Dominik W. Feger
